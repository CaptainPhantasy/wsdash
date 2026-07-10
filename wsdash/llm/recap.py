"""'Where did I leave off?' — scans local AI-harness logs and git state.

Harness coverage (CLI and Desktop variants where they exist locally):
- Claude Code:      ~/.claude/projects/<proj>/*.jsonl  (CLI, desktop app, claude.ai/code
                    sessions all land here when they touch this machine)
- Codex:            ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl (originator field
                    distinguishes 'Codex Desktop' vs CLI)
- floyd family:     ~/.floyd*/floyd.db sqlite (floyd, ff, superfloyd, forks, ...) —
                    OhMyFloyd/ff/superfloyd harnesses
- OMP:              ~/.omp/agent/agent.db threads table + harness audit log —
                    OhMyPi / OpenMythos runtimes (source_kind distinguishes origin)

Every scanner is defensive: missing dirs => harness reported unavailable; parse
errors are contained per-file/per-row and noted, never fatal.
"""
import contextlib
import glob
import json
import os
import sqlite3
import time

from .. import config, gitutil
from . import envfile

HOME = os.path.expanduser("~")
MAX_JSONL_BYTES = config.LIMITS.get("recap_max_jsonl_bytes", 8 * 1024 * 1024)
MAX_JSONL_LINES = config.LIMITS.get("recap_max_jsonl_lines_per_file", 200)
MAX_JSONL_LINE_BYTES = config.LIMITS.get("recap_max_jsonl_line_bytes", 512 * 1024)


def _iso_to_ts(s):
    import datetime
    with contextlib.suppress(Exception):
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    return 0.0


def _norm_ts(v) -> float:
    """Seconds vs milliseconds by magnitude."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 1e12 else v


def _text_of(content) -> str:
    """Claude/Codex message content: string or list of typed blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") in ("text", "input_text"):
                out.append(b.get("text", ""))
        return "\n".join(out)
    return ""


def _clip(s: str, n: int = 200) -> str:
    s = " ".join((s or "").split())
    return s[: n - 1] + "…" if len(s) > n else s


INSTRUCTION_PREFIXES = ("# AGENTS.md", "<INSTRUCTIONS>", "<system-con", "<system-reminder")


def _is_instruction_blob(text: str) -> bool:
    """Harness-injected 'user' messages (AGENTS.md dumps etc.) are not real asks."""
    head = text.lstrip()[:200]
    return any(p in head for p in INSTRUCTION_PREFIXES) or head.startswith("<")


_NOISE_LINE = ("drwx", "-rw-", "lrwx", "diff --git", "+++", "---", "index ", "total ")


def _title_from(text: str, fallback: str = "") -> str:
    """First sentence-like line: ≥3 words, not terminal-paste noise."""
    for line in (text or "").splitlines():
        line = line.strip()
        if (len(line.split()) >= 3 and not line.startswith(_NOISE_LINE)
                and not line.startswith(("#", "|", "$", ">", "{", "["))):
            return _clip(line, 100)
    return _clip(text or fallback, 100)


def _tail_lines(path: str, max_bytes: int = config.LIMITS.get("recap_tail_bytes", 2 * 1024 * 1024)) -> list:
    """Last lines of a file by seeking — never loads the whole file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read(max_bytes)
        if size > max_bytes:  # drop the probably-partial first line
            data = data.split(b"\n", 1)[-1]
        return data.decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _iter_jsonl(path: str):
    """Memory-flat jsonl iterator: yields one parsed record at a time and never
    materializes the file. Oversized transcripts are bounded to the first 200
    lines plus a seek-read 2MB tail."""
    try:
        oversized = os.path.getsize(path) > MAX_JSONL_BYTES
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if oversized and i >= MAX_JSONL_LINES:
                    break
                if len(line) > MAX_JSONL_LINE_BYTES:  # multi-MB single records: skip, don't parse
                    continue
                with contextlib.suppress(json.JSONDecodeError):
                    yield json.loads(line)
        if oversized:
            for line in _tail_lines(path):
                if len(line) > MAX_JSONL_LINE_BYTES:
                    continue
                with contextlib.suppress(json.JSONDecodeError):
                    yield json.loads(line)
    except OSError:
        return


# ---- scanners -------------------------------------------------------------------

def scan_claude(since: float, now: float) -> dict:
    root = os.path.join(HOME, ".claude", "projects")
    h = {"name": "claude-code", "available": os.path.isdir(root), "sessions": [], "notes": []}
    if not h["available"]:
        h["notes"].append(f"{root} not found")
        return h
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < since:
                continue
        except OSError:
            continue
        cwd, title, first_user, last_user, last_assistant = "", "", "", "", ""
        ts_first = ts_last = 0.0
        n_user = 0
        for r in _iter_jsonl(path):
            if not isinstance(r, dict):
                continue
            cwd = r.get("cwd") or cwd
            ts = _iso_to_ts(r.get("timestamp", "")) if r.get("timestamp") else 0.0
            if ts:
                ts_first = ts_first or ts
                ts_last = max(ts_last, ts)
            if r.get("type") == "summary":
                title = r.get("summary", "") or title
            msg = r.get("message") or {}
            if r.get("type") == "user" and isinstance(msg, dict):
                text = _text_of(msg.get("content"))[:4096]  # clip early: flat memory
                if text and not _is_instruction_blob(text):
                    n_user += 1
                    first_user = first_user or text
                    last_user = text
            elif r.get("type") == "assistant" and isinstance(msg, dict):
                t = _text_of(msg.get("content"))[:4096]
                last_assistant = t or last_assistant
        h["sessions"].append({
            "id": os.path.basename(path)[:-6], "origin": "cli/desktop/web",
            "project": cwd, "title": title and _clip(title, 100) or _title_from(first_user),
            "started": ts_first, "ended": ts_last or os.path.getmtime(path),
            "n_user_msgs": n_user, "last_user": _clip(last_user),
            "last_assistant": _clip(last_assistant, 400),
        })
    return h


def scan_codex(since: float, now: float) -> dict:
    root = os.path.join(HOME, ".codex", "sessions")
    h = {"name": "codex", "available": os.path.isdir(root), "sessions": [], "notes": []}
    if not h["available"]:
        h["notes"].append(f"{root} not found")
        return h
    for path in glob.glob(os.path.join(root, "*", "*", "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < since:
                continue
        except OSError:
            continue
        cwd = origin = sid = ""
        first_user = last_user = ""
        n_user = 0
        ts_first = ts_last = 0.0
        for r in _iter_jsonl(path):
            if not isinstance(r, dict):
                continue
            ts = _iso_to_ts(r.get("timestamp", "")) if r.get("timestamp") else 0.0
            if ts:
                ts_first = ts_first or ts
                ts_last = max(ts_last, ts)
            p = r.get("payload") or {}
            if r.get("type") == "session_meta":
                cwd = p.get("cwd", cwd)
                origin = p.get("originator", origin)
                sid = p.get("session_id") or p.get("id") or sid
            text = ""
            if p.get("type") == "message" and p.get("role") == "user":
                text = _text_of(p.get("content"))
            elif p.get("type") == "user_message":
                text = p.get("message", "") if isinstance(p.get("message"), str) \
                    else _text_of(p.get("message"))
            if text and not _is_instruction_blob(text):
                n_user += 1
                text = text[:4096]  # clip early: flat memory
                first_user = first_user or text
                last_user = text
        h["sessions"].append({
            "id": sid or os.path.basename(path)[:-6],
            "origin": origin or "cli", "project": cwd,
            "title": _title_from(first_user), "started": ts_first,
            "ended": ts_last or os.path.getmtime(path),
            "n_user_msgs": n_user, "last_user": _clip(last_user), "last_assistant": "",
        })
    return h


def _floyd_label(dirname: str) -> str:
    base = dirname.lstrip(".")  # .floyd-ff -> floyd-ff
    return {"floyd": "floyd (OhMyFloyd)", "floyd-ff": "ff",
            "floyd-superfloyd": "superfloyd"}.get(base, base)


def scan_floyd_family(since: float, now: float) -> list:
    out = []
    for d in sorted(glob.glob(os.path.join(HOME, ".floyd*"))):
        db = os.path.join(d, "floyd.db")
        if not os.path.isfile(db):
            continue
        h = {"name": _floyd_label(os.path.basename(d)), "available": True,
             "sessions": [], "notes": [f"db: {db}"]}
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
            cur = con.execute(
                "select id, title, message_count, updated_at from sessions "
                "order by updated_at desc limit 50")
            for sid, title, n, upd in cur.fetchall():
                ts = _norm_ts(upd)
                if ts < since:
                    continue
                last_user = last_assistant = ""
                with contextlib.suppress(sqlite3.Error):
                    for role, parts in con.execute(
                            "select role, parts from messages where session_id=? "
                            "order by created_at desc limit 8", (sid,)):
                        text = ""
                        with contextlib.suppress(json.JSONDecodeError, TypeError):
                            for part in json.loads(parts or "[]"):
                                data = part.get("data") or {}
                                if part.get("type") == "text":
                                    text += data.get("text", "")
                        if role == "user" and text and not last_user:
                            last_user = text
                        if role == "assistant" and text and not last_assistant:
                            last_assistant = text
                h["sessions"].append({
                    "id": sid, "origin": "cli", "project": "",
                    "title": _clip(title, 100), "started": 0.0, "ended": ts,
                    "n_user_msgs": n, "last_user": _clip(last_user),
                    "last_assistant": _clip(last_assistant, 400),
                })
            con.close()
        except sqlite3.Error as exc:
            h["notes"].append(f"sqlite error: {exc}")
        out.append(h)  # always report a found db, even when quiet (0 sessions)
    if not out:
        out.append({"name": "floyd family (floyd/ff/superfloyd)", "available": False,
                    "sessions": [], "notes": ["no ~/.floyd*/floyd.db found"]})
    return out


def scan_omp(since: float, now: float) -> dict:
    db = os.path.join(HOME, ".omp", "agent", "agent.db")
    h = {"name": "omp (OhMyPi/OpenMythos)", "available": os.path.isfile(db),
         "sessions": [], "notes": []}
    if not h["available"]:
        h["notes"].append(f"{db} not found")
        return h
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        for tid, upd, cwd, kind in con.execute(
                "select id, updated_at, cwd, source_kind from threads "
                "order by updated_at desc limit 100"):
            ts = _norm_ts(upd)
            if ts < since:
                continue
            h["sessions"].append({
                "id": str(tid), "origin": kind or "cli", "project": cwd or "",
                "title": f"{kind or 'thread'} in {os.path.basename(cwd or '') or '?'}",
                "started": 0.0, "ended": ts, "n_user_msgs": 0,
                "last_user": "", "last_assistant": "",
            })
        con.close()
    except sqlite3.Error as exc:
        h["notes"].append(f"sqlite error: {exc}")
    audit = envfile.llm_config()["omp_audit_log"]
    if os.path.isfile(audit):
        n_events, last_ts = 0, 0.0
        for line in _tail_lines(audit):
            with contextlib.suppress(json.JSONDecodeError):
                rec = json.loads(line)
                ts = _norm_ts(rec.get("timestamp"))
                if ts >= since:
                    n_events += 1
                    last_ts = max(last_ts, ts)
        h["notes"].append(f"audit.log: {n_events} events in window"
                          + (f", last {time.strftime('%H:%M', time.localtime(last_ts))}" if last_ts else ""))
    return h


# ---- git activity + open items ----------------------------------------------------

def git_activity(path: str, since: float) -> dict:
    if not os.path.isdir(path) or not gitutil.is_repo(path):
        return {"is_repo": False}
    since_arg = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(since))
    _, branch = gitutil.run(["branch", "--show-current"], path)
    _, log = gitutil.run(["log", f"--since={since_arg}", "--pretty=%h %ad %s",
                          "--date=format:%H:%M", "-n", "20"], path)
    _, stat = gitutil.run(["diff", "--shortstat", "HEAD"], path)  # one summary line
    n_status = [0]
    gitutil.run_stream(["status", "--porcelain"], path,  # streamed count: flat memory
                       line_cb=lambda raw: n_status.__setitem__(0, n_status[0] + bool(raw.strip())))
    return {
        "is_repo": True, "branch": branch.strip(),
        "commits": log.strip().splitlines(),
        "uncommitted_summary": stat.strip() or "clean",
        "uncommitted_files": n_status[0],
    }


def open_items(path: str, cfg: dict) -> list:
    """Concrete unfinished-work indicators, reusing the wsdash signal providers."""
    items = []
    if not os.path.isdir(path):
        return ["path missing (disconnected volume?)"]
    if gitutil.is_repo(path):
        from .. import providers as providers_pkg, scoring, store
        ws = {"id": store.ws_id(path), "path": os.path.realpath(path),
              "name": os.path.basename(path), "kind": "repo"}
        doc = scoring.compute_score(ws, cfg)
        for s in doc["signals"]:
            if not s.get("error") and s["value"] > 0:
                items.append(s["detail"])
        if doc["score"] >= float(cfg.get("incomplete_threshold", 10)):
            items.insert(0, f"dirtiness score {doc['score']} (INCOMPLETE)")
    return items


def project_diff(path: str, max_bytes: int = config.LIMITS.get("recap_project_diff_max_bytes", 20_000)) -> str:
    """Bounded 'what did I change here': uncommitted diff + last day's commits."""
    if not os.path.isdir(path):
        return f"ERROR: {path} does not exist"
    if not gitutil.is_repo(path):
        return f"{path} is not a git repository"
    _, log = gitutil.run(["log", "--since=36 hours ago", "--pretty=%h %ad %s",
                          "--date=format:%a %H:%M", "-n", "20"], path)
    # capped streaming capture: never hold a multi-MB diff in memory
    kept, total = [], [0]

    def _line(raw: bytes):
        total[0] += len(raw) + 1
        if total[0] <= max_bytes:
            kept.append(raw.decode("utf-8", errors="replace"))

    gitutil.run_stream(["diff", "HEAD", "--no-color"], path, line_cb=_line)
    _, untracked = gitutil.run(["ls-files", "--others", "--exclude-standard"], path)
    out = [f"# {path}", "## commits (last 36h)", log.strip() or "(none)",
           "## uncommitted diff"]
    d = "\n".join(kept).strip() or "(clean)"
    if total[0] > max_bytes:
        d += f"\n… truncated ({total[0]} bytes total)"
    out.append(d)
    if untracked.strip():
        out.append("## untracked files\n" + untracked.strip())
    return "\n".join(out)


# ---- top level -----------------------------------------------------------------

def _is_project_path(p: str) -> bool:
    """Exclude $HOME, /, and bare volume roots unless they are actual repos."""
    import re
    real = os.path.realpath(p)
    if real in ("/", HOME) or re.fullmatch(r"/Volumes/[^/]+", real):
        return gitutil.is_repo(real)
    return True


def scan(cfg: dict, hours: float = 24.0) -> dict:
    hours = min(max(float(hours), 1.0), 336.0)  # clamp: 1h .. 14 days
    now = time.time()
    since = now - hours * 3600
    harnesses = [scan_claude(since, now), scan_codex(since, now)]
    harnesses += scan_floyd_family(since, now)
    harnesses.append(scan_omp(since, now))

    proj_paths = []
    for h in harnesses:
        for s in h["sessions"]:
            p = s.get("project")
            if p and os.path.isdir(p) and p not in proj_paths and _is_project_path(p):
                proj_paths.append(p)
    projects = []
    for p in sorted(proj_paths):
        act = git_activity(p, since)
        projects.append({"path": p, **act, "open_items": open_items(p, cfg)})
    return {"generated_at": now, "window_hours": hours,
            "harnesses": harnesses, "projects": projects}


def render(doc: dict) -> str:
    out = [f"recap — last {doc['window_hours']:.0f}h "
           f"({time.strftime('%a %d %b %H:%M', time.localtime(doc['generated_at']))})", ""]
    for h in doc["harnesses"]:
        n = len(h["sessions"])
        flag = "" if h["available"] else "  [unavailable]"
        out.append(f"■ {h['name']}: {n} session(s){flag}")
        for note in h.get("notes", []):
            out.append(f"    ({note})")
        for s in sorted(h["sessions"], key=lambda x: -x["ended"])[:8]:
            when = time.strftime("%a %H:%M", time.localtime(s["ended"])) if s["ended"] else "?"
            proj = f"  [{s['project']}]" if s.get("project") else ""
            out.append(f"    {when}  {s['origin']:<14} {s['title'] or s['id']}{proj}")
            if s.get("last_user"):
                out.append(f"           last ask: {s['last_user'][:120]}")
    out.append("")
    out.append("■ projects touched")
    if not doc["projects"]:
        out.append("    (none resolved from session logs)")
    for p in doc["projects"]:
        out.append(f"  • {p['path']}" + (f"  ({p.get('branch')})" if p.get("branch") else ""))
        if p.get("is_repo"):
            for c in p.get("commits", [])[:5]:
                out.append(f"      commit {c}")
            out.append(f"      uncommitted: {p.get('uncommitted_summary', '?')} "
                       f"({p.get('uncommitted_files', 0)} files)")
        for item in p.get("open_items", [])[:6]:
            out.append(f"      open: {item}")
    return "\n".join(out)

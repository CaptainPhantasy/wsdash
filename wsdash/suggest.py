"""Predictive context awareness — a LAZY layer: this module is only imported when
`wsdash suggest` is invoked. Nothing here runs in the background, ever.

Three deterministic analyses:
1. Branch dependencies — shared name tokens between your current/unmerged branches
   and other workspaces' names/branches.
2. Recent activity clusters — workspaces whose events co-occur within 30-minute
   windows in the event log.
3. Project interdependencies — local path links in package.json (file:/link:),
   requirements*.txt (-e ./...), and go.mod replace directives.
"""
import json
import os
import re

from . import gitutil, store

WINDOW = 1800.0  # activity-cluster window, seconds
TOKEN = re.compile(r"[a-z0-9]{3,}")


def _tokens(s: str) -> set:
    return set(TOKEN.findall(s.lower()))


def _branches(ws: dict) -> list:
    if ws.get("kind") not in ("repo", "worktree") or ws.get("missing"):
        return []
    rc, out = gitutil.run(["for-each-ref", "refs/heads", "--format=%(refname:short)"], ws["path"])
    return [b.strip() for b in out.splitlines() if b.strip()] if rc == 0 else []


def _local_dep_paths(ws: dict) -> list:
    """Local filesystem dependency targets declared by this workspace."""
    paths, root = [], ws["path"]
    pj = os.path.join(root, "package.json")
    try:
        with open(pj, "r", encoding="utf-8") as f:
            data = json.load(f)
        for section in ("dependencies", "devDependencies"):
            for spec in (data.get(section) or {}).values():
                if isinstance(spec, str) and spec.startswith(("file:", "link:")):
                    paths.append(os.path.normpath(os.path.join(root, spec.split(":", 1)[1])))
    except (OSError, json.JSONDecodeError):
        pass
    for fn in ("requirements.txt", "requirements-dev.txt"):
        try:
            with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("-e ") and ("/" in line or line.startswith("-e .")):
                        paths.append(os.path.normpath(os.path.join(root, line[3:].strip())))
        except OSError:
            continue
    try:
        with open(os.path.join(root, "go.mod"), "r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"replace\s+\S+\s*=>\s*(\.{1,2}/\S+)", line)
                if m:
                    paths.append(os.path.normpath(os.path.join(root, m.group(1))))
    except OSError:
        pass
    return paths


def suggest(cfg: dict, reg: dict, scores: dict) -> list:
    """Returns ranked [{path, name, score, reasons: [...]}]."""
    wss = {wid: ws for wid, ws in reg["workspaces"].items()}
    reasons: dict[str, list] = {wid: [] for wid in wss}

    # 1. branch dependency token overlap
    branch_tokens = {wid: _tokens(" ".join(_branches(ws)) + " " + ws["name"])
                     for wid, ws in wss.items()}
    for a, ta in branch_tokens.items():
        for b, tb in branch_tokens.items():
            if a >= b:
                continue
            common = (ta & tb) - {"main", "master", "feature", "branch"}
            if common:
                lbl = f"shared branch/name tokens: {', '.join(sorted(common)[:3])}"
                reasons[a].append(("branch", 1.0, f"{lbl} with {wss[b]['name']}"))
                reasons[b].append(("branch", 1.0, f"{lbl} with {wss[a]['name']}"))

    # 2. activity clusters from the event log
    events = [e for e in store.read_events() if e.get("ws") in wss]
    events.sort(key=lambda e: e["ts"])
    for i, e in enumerate(events):
        for f in events[i + 1:]:
            if f["ts"] - e["ts"] > WINDOW:
                break
            if f["ws"] != e["ws"]:
                reasons[e["ws"]].append(("cluster", 0.5, f"active alongside {wss[f['ws']]['name']}"))
                reasons[f["ws"]].append(("cluster", 0.5, f"active alongside {wss[e['ws']]['name']}"))

    # 3. project interdependencies via local dep paths
    real_to_wid = {os.path.realpath(ws["path"]): wid for wid, ws in wss.items()}
    for wid, ws in wss.items():
        if ws.get("missing"):
            continue
        for dep in _local_dep_paths(ws):
            target = real_to_wid.get(os.path.realpath(dep))
            if target and target != wid:
                reasons[wid].append(("dep", 1.5, f"depends on {wss[target]['name']}"))
                reasons[target].append(("dep", 1.5, f"dependency of {wss[wid]['name']}"))

    out = []
    for wid, rs in reasons.items():
        score = scores.get(wid, {}).get("score", 0.0)
        rank = score * 0.05 + sum(w for _, w, _ in rs)
        if rank <= 0:
            continue
        seen, texts = set(), []
        for _, _, t in sorted(rs, key=lambda r: -r[1]):
            if t not in seen:
                seen.add(t)
                texts.append(t)
        out.append({"path": wss[wid]["path"], "name": wss[wid]["name"],
                    "score": score, "rank": round(rank, 2), "reasons": texts[:5]})
    out.sort(key=lambda s: (-s["rank"], s["name"]))
    return out

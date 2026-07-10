"""State store: atomic JSON writes, corruption quarantine, flock, score cache, event log.

Fault tolerance model:
- Every write is tmp-file + os.replace (atomic on APFS) => interruptions never leave
  half-written state.
- Every read quarantines unparseable files (renamed *.corrupt-<ts>) and returns a
  default so the system self-heals on the next recompute.
- A single advisory flock serializes registry/score mutations across concurrent
  launchd jobs and git hooks; lock acquisition is bounded (default 5s) and may
  be enforced as required by callers.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from collections import deque
import tempfile
import time

from . import config


def state_dir() -> str:
    return os.path.join(config.home(), "state")


def log_dir() -> str:
    return os.path.join(config.home(), "log")


def ensure_dirs() -> None:
    for d in (config.home(), state_dir(), log_dir(),
              os.path.join(config.home(), "providers"),
              os.path.join(config.home(), "views")):
        os.makedirs(d, exist_ok=True)


def ws_id(path: str) -> str:
    return hashlib.sha1(os.path.realpath(path).encode()).hexdigest()[:12]


def atomic_write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        quarantine = f"{path}.corrupt-{int(time.time())}"
        with contextlib.suppress(OSError):
            os.replace(path, quarantine)
        return default


@contextlib.contextmanager
def locked(timeout: float | None = None, require: bool = False):
    """Bounded exclusive lock; on timeout, proceed unlocked (atomic writes keep us safe)."""
    if timeout is None:
        timeout = config.LIMITS.get("store_lock_timeout_seconds", 5.0)
    ensure_dirs()
    lf = open(os.path.join(config.home(), "lock"), "a+")
    got = False
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                time.sleep(0.05)
        if require and not got:
            raise TimeoutError("store lock not acquired within timeout")
        yield got
    finally:
        if got:
            with contextlib.suppress(OSError):
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        lf.close()


# ---- registry ----------------------------------------------------------------

def registry_path() -> str:
    return os.path.join(state_dir(), "registry.json")


def load_registry() -> dict:
    return load_json(registry_path(), {"version": 1, "updated_at": 0, "workspaces": {}})


def save_registry(reg: dict) -> None:
    reg["updated_at"] = time.time()
    atomic_write_json(registry_path(), reg)


# ---- score cache ---------------------------------------------------------------

def score_path(wsid: str) -> str:
    return os.path.join(state_dir(), f"score-{wsid}.json")


def is_fresh(doc, ttl: float, now: float | None = None) -> bool:
    if not doc:
        return False
    now = time.time() if now is None else now
    return (now - doc.get("computed_at", 0)) < ttl


# ---- event log (append-only, size-capped) --------------------------------------

def events_path() -> str:
    return os.path.join(log_dir(), "events.jsonl")


def append_event(kind: str, wsid: str, path: str, extra: dict | None = None) -> None:
    ensure_dirs()
    rec = {"ts": time.time(), "kind": kind, "ws": wsid, "path": path}
    if extra:
        rec.update(extra)
    p = events_path()
    max_bytes = int(config.LIMITS.get("event_log_max_bytes", 512 * 1024))
    max_lines = int(config.LIMITS.get("event_log_tail_lines", 400))
    try:
        if os.path.exists(p) and os.path.getsize(p) > max_bytes:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-max_lines:]
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(tail)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError:
        pass  # event log is best-effort telemetry, never fatal


def read_events(limit: int = 2000) -> list:
    out = []
    try:
        with open(events_path(), "r", encoding="utf-8", errors="replace") as f:
            for line in deque(f, maxlen=max(1, limit)):
                with contextlib.suppress(json.JSONDecodeError):
                    out.append(json.loads(line))
    except OSError:
        pass
    return out

"""Signal 1: unstaged diff size in bytes."""
from .. import gitutil

NAME = "diff_bytes"
UNIT = "bytes"
WEIGHT = 0.25
CAP = 50_000  # bytes of unstaged diff at which the signal saturates


def applies_to(ws):
    return ws.get("kind") in ("repo", "worktree")


def collect(ws):
    # streamed byte count — memory stays flat even on 100MB+ diffs
    rc, b = gitutil.run_stream(["diff", "--no-color"], ws["path"])
    if rc != 0:
        raise RuntimeError(f"git diff rc={rc}")
    return {"value": b, "normalized": min(b / CAP, 1.0), "detail": f"{b} B unstaged"}

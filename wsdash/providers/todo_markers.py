"""Signal 6: new TODO/FIXME/HACK/XXX markers — added lines in the unstaged diff
plus markers in untracked files (bounded scan)."""
import os
import re

from .. import gitutil

NAME = "todo_markers"
UNIT = "markers"
WEIGHT = 0.15
CAP = 10
MARK_B = re.compile(rb"\b(TODO|FIXME|HACK|XXX)\b")
MAX_UNTRACKED_FILES = 100
MAX_FILE_BYTES = 256 * 1024


def applies_to(ws):
    return ws.get("kind") in ("repo", "worktree")


def collect(ws):
    counter = {"n": 0}

    def _line(raw: bytes):
        if raw.startswith(b"+") and not raw.startswith(b"+++") and MARK_B.search(raw):
            counter["n"] += 1

    rc, _ = gitutil.run_stream(["diff", "--unified=0", "--no-color"], ws["path"],
                               line_cb=_line)
    if rc != 0:
        raise RuntimeError(f"git diff rc={rc}")
    n = counter["n"]
    paths: list = []

    def _collect(raw: bytes):  # streamed: repos with millions of untracked paths stay flat
        if raw.strip() and len(paths) < MAX_UNTRACKED_FILES:
            paths.append(raw.decode("utf-8", "replace").strip())

    gitutil.run_stream(["ls-files", "--others", "--exclude-standard"], ws["path"],
                       line_cb=_collect)
    scanned = 0
    for rel in paths:
        p = os.path.join(ws["path"], rel)
        try:
            if os.path.getsize(p) > MAX_FILE_BYTES:
                continue
            with open(p, "rb") as f:
                data = f.read()
            if b"\0" in data[:1024]:
                continue
            n += len(MARK_B.findall(data))
            scanned += 1
        except OSError:
            continue
    return {"value": n, "normalized": min(n / CAP, 1.0),
            "detail": f"{n} new markers (diff + {scanned} untracked files)"}

"""Signal 4: hours since last touch (newest mtime among the workspace root, its
immediate entries, and .git/index|HEAD). Staler = more likely forgotten/incomplete."""
import contextlib
import os
import time

NAME = "last_touch"
UNIT = "hours"
WEIGHT = 0.15
CAP_HOURS = 168.0  # one week untouched saturates the signal


def applies_to(ws):
    return True


def newest_mtime(path: str) -> float:
    newest = 0.0
    with contextlib.suppress(OSError):
        newest = os.stat(path).st_mtime
    with contextlib.suppress(OSError):
        for e in os.scandir(path):
            with contextlib.suppress(OSError):
                newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
    for probe in ("index", "HEAD"):
        with contextlib.suppress(OSError):
            newest = max(newest, os.stat(os.path.join(path, ".git", probe)).st_mtime)
    return newest


def collect(ws):
    newest = newest_mtime(ws["path"])
    if newest <= 0:
        raise RuntimeError("no readable mtimes")
    hours = max(0.0, (time.time() - newest) / 3600.0)
    return {"value": round(hours, 2), "normalized": min(hours / CAP_HOURS, 1.0),
            "detail": f"{hours:.1f}h since last touch"}

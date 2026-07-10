"""Signal 3: stale (prunable or path-missing) linked worktrees of the repo."""
import os

from .. import gitutil

NAME = "stale_worktrees"
UNIT = "worktrees"
WEIGHT = 0.10
CAP = 3


def applies_to(ws):
    return ws.get("kind") == "repo"


def collect(ws):
    rc, out = gitutil.run(["worktree", "list", "--porcelain"], ws["path"])
    if rc != 0:
        raise RuntimeError(f"git worktree list rc={rc}")
    stale, blocks = 0, out.strip().split("\n\n")
    for block in blocks[1:]:  # first block is the main worktree
        path, prunable = "", False
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):].strip()
            elif line.startswith("prunable"):
                prunable = True
        if prunable or (path and not os.path.isdir(path)):
            stale += 1
    return {"value": stale, "normalized": min(stale / CAP, 1.0),
            "detail": f"{stale} stale of {max(len(blocks) - 1, 0)} linked"}

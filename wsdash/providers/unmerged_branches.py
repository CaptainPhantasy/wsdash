"""Signal 2: count of local branches not merged into the default branch."""
from .. import gitutil

NAME = "unmerged_branches"
UNIT = "branches"
WEIGHT = 0.15
CAP = 5


def applies_to(ws):
    return ws.get("kind") in ("repo", "worktree")


def collect(ws):
    base = gitutil.default_branch(ws["path"])
    rc, out = gitutil.run(
        ["for-each-ref", "refs/heads", f"--no-merged={base}", "--format=%(refname:short)"],
        ws["path"])
    if rc != 0:
        raise RuntimeError(f"git for-each-ref rc={rc}")
    names = [n for n in out.splitlines() if n.strip() and n.strip() != base]
    n = len(names)
    return {"value": n, "normalized": min(n / CAP, 1.0),
            "detail": f"{n} unmerged into {base}" + (f" ({', '.join(names[:3])})" if n else "")}

"""Workspace discovery: git repos/worktrees under roots, shell session dirs,
and editor workspace directories (VS Code / Cursor workspaceStorage).

Discovery is bounded (max_depth) and incremental: sync_registry() merges into the
existing registry, marking vanished paths missing=True (disconnected) instead of
dropping them, so state survives unplugged volumes and deleted checkouts.
"""
import glob
import json
import os
import time
import urllib.parse

from . import config, gitutil, store


def _worktrees_of(repo_path: str) -> list:
    rc, out = gitutil.run(["worktree", "list", "--porcelain"], repo_path)
    if rc != 0:
        return []
    paths = []
    for block in out.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("worktree "):
                paths.append(line[len("worktree "):].strip())
    return paths


def _editor_workspaces(cfg: dict) -> list:
    found = []
    for pattern in cfg.get("editor_workspace_globs", []):
        for wj in glob.glob(os.path.expanduser(pattern)):
            try:
                with open(wj, "r", encoding="utf-8") as f:
                    folder = json.load(f).get("folder", "")
            except (OSError, json.JSONDecodeError):
                continue
            if not folder.startswith("file://"):
                continue
            path = urllib.parse.unquote(urllib.parse.urlparse(folder).path)
            if os.path.isdir(path):
                found.append((os.path.getmtime(wj), path))
    found.sort(reverse=True)
    return [p for _, p in found[: cfg.get("max_editor_workspaces", 50)]]


def find_workspaces(cfg: dict) -> dict:
    """Returns {ws_id: workspace-dict}. Bounded scan, no polling — call on demand/event."""
    ignore = set(cfg.get("ignore_dirs", []))
    out: dict[str, dict] = {}

    def add(path: str, kind: str, source: str, repo_root: str | None = None):
        real = os.path.realpath(path)
        wid = store.ws_id(real)
        ws = out.get(wid)
        if ws is None:
            out[wid] = {
                "id": wid, "path": real, "name": os.path.basename(real) or real,
                "kind": kind, "repo_root": repo_root or (real if kind == "repo" else None),
                "sources": [source],
            }
        else:
            if source not in ws["sources"]:
                ws["sources"].append(source)
            if kind in ("repo", "worktree") and ws["kind"] not in ("repo", "worktree"):
                ws["kind"], ws["repo_root"] = kind, repo_root or real

    for root in config.roots(cfg):
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                if not e.is_dir(follow_symlinks=False) or e.name.startswith(".") or e.name in ignore:
                    continue
                p = e.path
                if gitutil.is_repo(p):
                    add(p, "repo", "scan")
                    for wt in _worktrees_of(p):
                        if os.path.realpath(wt) != os.path.realpath(p) and os.path.isdir(wt):
                            add(wt, "worktree", "scan", repo_root=os.path.realpath(p))
                elif depth == 0:
                    add(p, "session-dir", "scan")
                    if depth + 1 < cfg.get("max_depth", 2):
                        stack.append((p, depth + 1))
                elif depth + 1 < cfg.get("max_depth", 2):
                    stack.append((p, depth + 1))

    for p in _editor_workspaces(cfg):
        add(p, "repo" if gitutil.is_repo(p) else "session-dir", "editor")
    return out


def sync_registry(cfg: dict) -> dict:
    """Incremental merge of a fresh discovery into the persisted registry."""
    reg = store.load_registry()
    discovered = find_workspaces(cfg)
    now = time.time()
    for wid, ws in discovered.items():
        prev = reg["workspaces"].get(wid, {})
        ws["first_seen"] = prev.get("first_seen", now)
        ws["missing"] = False
        reg["workspaces"][wid] = ws
    for wid, ws in reg["workspaces"].items():
        if wid not in discovered:
            ws["missing"] = not os.path.isdir(ws.get("path", ""))
    store.save_registry(reg)
    return reg


def register_adhoc(cfg: dict, path: str) -> dict:
    """Register a single workspace outside the scan roots (used by git hooks)."""
    real = os.path.realpath(path)
    reg = store.load_registry()
    wid = store.ws_id(real)
    if wid not in reg["workspaces"]:
        kind = "repo" if gitutil.is_repo(real) else "session-dir"
        reg["workspaces"][wid] = {
            "id": wid, "path": real, "name": os.path.basename(real) or real,
            "kind": kind, "repo_root": real if kind == "repo" else None,
            "sources": ["hook"], "first_seen": time.time(), "missing": False,
        }
        store.save_registry(reg)
    return reg["workspaces"][wid]

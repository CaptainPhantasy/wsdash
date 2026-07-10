"""Event-driven recomputation. Invoked ONLY by launchd WatchPaths jobs and git
hooks — the process handles one event batch, updates only affected caches
(incremental state synchronization), appends telemetry, and exits.
"""
import os

from . import config, discover, scoring, store
from .providers.last_touch import newest_mtime


def handle_fs(cfg: dict) -> list:
    """A watched path changed. Re-sync the registry incrementally, then recompute
    only workspaces whose content is newer than their cached score."""
    changed = []
    with store.locked():
        reg = discover.sync_registry(cfg)
        provs = None
        for wid, ws in reg["workspaces"].items():
            cached = store.load_json(store.score_path(wid))
            if cached and (ws.get("missing") or not os.path.isdir(ws["path"])):
                if cached.get("status") != "disconnected":
                    doc = scoring.compute_score(ws, cfg)
                    store.atomic_write_json(store.score_path(wid), doc)
                    changed.append(wid)
                continue
            if cached and newest_mtime(ws["path"]) <= cached.get("computed_at", 0):
                continue  # untouched since last score — skip (incremental)
            if provs is None:
                from . import providers as providers_pkg
                provs, _ = providers_pkg.load_providers()
            doc = scoring.compute_score(ws, cfg, provs)
            store.atomic_write_json(store.score_path(wid), doc)
            changed.append(wid)
        store.append_event("fs", ",".join(changed) or "-", "watchpaths", {"n": len(changed)})
        _flag_watch_drift(cfg, reg)
    return changed


def handle_git(cfg: dict, path: str) -> str | None:
    """A git hook fired in `path`. Recompute that single workspace only."""
    if not path or not os.path.isdir(path):
        return None
    with store.locked():
        ws = discover.register_adhoc(cfg, path)
        doc = scoring.compute_score(ws, cfg)
        store.atomic_write_json(store.score_path(ws["id"]), doc)
        store.append_event("git", ws["id"], ws["path"], {"score": doc["score"]})
    return ws["id"]


def _flag_watch_drift(cfg: dict, reg: dict) -> None:
    """If the workspace set changed since the launchd plist was generated, drop a
    marker; `wsdash install` / `wsdash doctor` pick it up. We never reload launchd
    from inside a launchd job (it would kill our own process tree)."""
    from . import installer
    plist = installer.plist_path(cfg)
    if not os.path.exists(plist):
        return
    current = set(installer.watch_paths(cfg, reg))
    installed = set(installer.read_plist_watch_paths(plist))
    marker = os.path.join(config.home(), "watch-drift")
    if current != installed:
        with open(marker, "w", encoding="utf-8") as f:
            f.write("stale\n")
    elif os.path.exists(marker):
        os.unlink(marker)

"""Dirtiness scoring: weighted sum of normalized signals, 0–100, cached with TTL.

Recomputation happens ONLY when (a) an fs/git event targets the workspace, or
(b) an on-demand invocation finds the cache expired (>= cache_ttl_seconds).
There is no polling and no resident process.
"""
import os
import time

from . import providers as providers_pkg
from . import store


def compute_score(ws: dict, cfg: dict, provs=None) -> dict:
    if provs is None:
        provs, _ = providers_pkg.load_providers()
    prev = store.load_json(store.score_path(ws["id"]))
    if ws.get("missing") or not os.path.isdir(ws["path"]):
        doc = prev or _empty_doc(ws)
        doc["status"] = "disconnected"
        doc["computed_at"] = time.time()
        return doc

    signals, acc, total_w = [], 0.0, 0.0
    for mod in provs:
        sig = providers_pkg.run_provider(mod, ws)
        w = providers_pkg.weight_for(mod, cfg)
        sig["weight"] = w
        if not sig["error"]:
            acc += w * sig["normalized"]
            total_w += w
        signals.append(sig)
    score = round(100.0 * acc / total_w, 1) if total_w > 0 else 0.0
    status = "incomplete" if score >= float(cfg.get("incomplete_threshold", 15.0)) else "ok"
    return {
        "version": 1, "id": ws["id"], "path": ws["path"], "name": ws["name"],
        "kind": ws["kind"], "computed_at": time.time(), "score": score,
        "status": status, "signals": signals,
    }


def _empty_doc(ws: dict) -> dict:
    return {"version": 1, "id": ws["id"], "path": ws["path"], "name": ws["name"],
            "kind": ws.get("kind", "?"), "computed_at": 0, "score": 0.0,
            "status": "disconnected", "signals": []}


def get_score(ws: dict, cfg: dict, force: bool = False, provs=None):
    """Returns (doc, origin) where origin is 'cache' or 'computed'."""
    cached = store.load_json(store.score_path(ws["id"]))
    if not force and store.is_fresh(cached, float(cfg.get("cache_ttl_seconds", 300))):
        return cached, "cache"
    doc = compute_score(ws, cfg, provs)
    store.atomic_write_json(store.score_path(ws["id"]), doc)
    return doc, "computed"

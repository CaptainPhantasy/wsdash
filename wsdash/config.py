"""Configuration: defaults merged with ~/.wsdash/config.json (WSDASH_HOME override)."""
import copy
import json
import os

DEFAULTS = {
    "roots": ["~/sessions"],
    "max_depth": 2,
    "cache_ttl_seconds": 300,          # 5-minute score cache expiration
    "incomplete_threshold": 10.0,      # score >= threshold => surfaced as INCOMPLETE
    "editor_workspace_globs": [
        "~/Library/Application Support/Code/User/workspaceStorage/*/workspace.json",
        "~/Library/Application Support/Cursor/User/workspaceStorage/*/workspace.json",
    ],
    "max_editor_workspaces": 50,
    "weights": {
        "diff_bytes": 0.25,
        "unmerged_branches": 0.15,
        "stale_worktrees": 0.10,
        "last_touch": 0.15,
        "failing_tests": 0.20,
        "todo_markers": 0.15,
    },
    "launchd_label": "com.douglastalley.wsdash",
    "ignore_dirs": ["node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"],
}


LIMITS = {
    "store_lock_timeout_seconds": 5.0,
    "event_log_max_bytes": 512 * 1024,
    "event_log_tail_lines": 400,
    "chat_mode_default": "ask",
    "chat_max_tool_rounds": 20,
    "chat_tool_output_bytes": 60_000,
    "recap_max_jsonl_bytes": 8 * 1024 * 1024,
    "recap_max_jsonl_lines_per_file": 200,
    "recap_max_jsonl_line_bytes": 512 * 1024,
    "recap_project_diff_max_bytes": 20_000,
    "recap_tail_bytes": 2 * 1024 * 1024,
    "recap_omp_audit_candidates": [
        "~/.omp/audit.log",
        "~/.omp/agent/.harness/audit.log",
    ],
    "memory_ceiling_mb": 50.0,
}


def home() -> str:
    return os.path.expanduser(os.environ.get("WSDASH_HOME", "~/.wsdash"))


def config_path() -> str:
    return os.path.join(home(), "config.json")


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            user = json.load(f)
    except (OSError, json.JSONDecodeError):
        user = {}
    for k, v in user.items():
        if k == "weights" and isinstance(v, dict):
            cfg["weights"].update(v)
        else:
            cfg[k] = v
    return cfg


def save(cfg: dict) -> None:
    from . import store
    store.ensure_dirs()
    store.atomic_write_json(config_path(), cfg)


def roots(cfg: dict) -> list:
    out = []
    for r in cfg.get("roots", []):
        p = os.path.expanduser(r)
        if os.path.isdir(p):
            out.append(os.path.realpath(p))
    return out

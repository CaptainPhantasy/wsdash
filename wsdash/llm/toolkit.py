"""Built-in (non-MCP) tools exposed to the LLM Partner. All read-only."""
import json

BUILTIN_SPECS = [
    {
        "name": "get_recap",
        "description": ("Scan local AI-harness logs (Claude Code, Codex CLI/Desktop, "
                        "floyd/ff/superfloyd, OMP/OhMyPi/OpenMythos) plus git activity for "
                        "the user's recent work. Returns per-harness sessions, per-project "
                        "commits/uncommitted changes, and concrete open items. Use this when "
                        "the user asks where they left off or what they were working on."),
        "input_schema": {"type": "object", "properties": {
            "hours": {"type": "number", "description": "lookback window, default 24"}}},
    },
    {
        "name": "project_diff",
        "description": ("Show what the user added/changed in ONE project: commits from the "
                        "last 36h plus the current uncommitted diff and untracked files."),
        "input_schema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "absolute project path"}},
            "required": ["path"]},
    },
    {
        "name": "workspace_scores",
        "description": ("wsdash dirtiness dashboard data: per-workspace 0-100 score from six "
                        "signals (unstaged diff bytes, unmerged branches, stale worktrees, "
                        "hours since touch, failing tests, new TODOs)."),
        "input_schema": {"type": "object", "properties": {}},
    },
]

BUILTIN_NAMES = {t["name"] for t in BUILTIN_SPECS}


def call_builtin(name: str, args: dict, cfg: dict) -> str:
    from . import recap
    if name == "get_recap":
        hours = float(args.get("hours") or 24)
        doc = recap.scan(cfg, hours=min(max(hours, 1), 24 * 14))
        return recap.render(doc)
    if name == "project_diff":
        return recap.project_diff(str(args.get("path", "")))
    if name == "workspace_scores":
        from .. import store
        reg = store.load_registry()
        docs = []
        for wid, ws in reg["workspaces"].items():
            d = store.load_json(store.score_path(wid))
            if d:
                docs.append({"path": d["path"], "score": d["score"], "status": d["status"],
                             "top_signals": [s["detail"] for s in d.get("signals", [])
                                             if not s.get("error") and s["value"] > 0]})
        return json.dumps(sorted(docs, key=lambda d: -d["score"]), indent=1)
    return f"ERROR: unknown builtin tool {name}"

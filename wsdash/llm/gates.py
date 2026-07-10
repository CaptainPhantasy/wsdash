"""Gated execution stages for tool use.

Modes and their decision per tool class:

              read           write          dangerous
  plan        deny(plan)     deny(plan)     deny(plan)    -- propose only
  ask         confirm        confirm        confirm
  allow       allow          confirm        confirm       -- "allow non-destructive"
  auto        allow          allow          confirm
  yolo        allow          allow          allow

Unknown tools are classified conservatively: read-looking names (read_/list_/
get_/search_) => read, anything else => write; process/config-mutating tools
are pinned dangerous.
"""

MODES = ["plan", "ask", "allow", "auto", "yolo"]

# Desktop Commander tool classification (pinned; heuristics cover the rest)
READ_TOOLS = {
    "read_file", "read_multiple_files", "list_directory", "get_file_info",
    "search_files", "search_code", "start_search", "get_more_search_results",
    "stop_search", "list_searches", "list_processes", "list_sessions",
    "read_process_output", "get_config", "get_usage_stats", "get_prompts",
    # wsdash built-ins (read-only by construction)
    "get_recap", "project_diff", "workspace_scores",
}
DANGEROUS_TOOLS = {
    "start_process", "interact_with_process", "kill_process", "force_terminate",
    "set_config_value", "execute_command", "run_command",
}
READ_PREFIXES = ("read_", "list_", "get_", "search_", "find_", "stat_")


def classify(tool_name: str) -> str:
    if tool_name in DANGEROUS_TOOLS:
        return "dangerous"
    if tool_name in READ_TOOLS or tool_name.startswith(READ_PREFIXES):
        return "read"
    return "write"


def decide(mode: str, tool_name: str) -> str:
    """→ 'allow' | 'confirm' | 'deny-plan'"""
    if mode not in MODES:
        raise ValueError(f"unknown mode '{mode}' (choose from {', '.join(MODES)})")
    if mode == "plan":
        return "deny-plan"
    if mode == "yolo":
        return "allow"
    cls = classify(tool_name)
    if mode == "ask":
        return "confirm"
    if mode == "allow":
        return "allow" if cls == "read" else "confirm"
    # auto
    return "confirm" if cls == "dangerous" else "allow"


PLAN_NOTICE = ("PLAN MODE: tool execution is disabled. Do not retry. Instead, lay out "
               "the exact call(s) you would make and what you expect them to do.")
DENY_NOTICE = ("DENIED by the user at the gate. Do not retry this call. Explain what "
               "you wanted to do and ask how to proceed.")

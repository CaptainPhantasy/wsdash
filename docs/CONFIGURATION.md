# wsdash Configuration Reference (0.2.0-beta.1)

Two files, one precedence rule: **real environment variables always win.**

## 1. `.env.local` — LLM Partner

Load order (later overrides earlier): `~/.wsdash/.env.local` → `./.env.local` (cwd)
→ process environment. Template: `.env.local.example`. Keep it `chmod 600`.

| Key | Default | Meaning |
|---|---|---|
| `WSDASH_LLM_PROVIDER` | `openai` | `openai` (any /chat/completions-compatible endpoint) or `anthropic` |
| `WSDASH_LLM_BASE_URL` | `https://api.openai.com/v1` / `https://api.anthropic.com` | Endpoint base. `/v1` and full `/chat/completions` forms both accepted |
| `WSDASH_LLM_API_KEY` | empty | Bearer (openai) / x-api-key (anthropic). Empty = keyless (local proxies). Falls back to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| `WSDASH_LLM_MODEL` | *(required)* | e.g. `glm-5.2`, `gpt-4.1`, `claude-sonnet-5` |
| `WSDASH_LLM_MAX_TOKENS` | `4096` | Invalid values fall back with a stderr warning |
| `WSDASH_LLM_TEMPERATURE` | `0.2` | Invalid values fall back with a stderr warning |
| `WSDASH_LLM_SYSTEM_PROMPT` | empty | Text appended to the system prompt |
| `WSDASH_LLM_SYSTEM_PROMPT_FILE` | `~/.wsdash/prompts/partner.md` | Full system-prompt replacement file |
| `WSDASH_MCP_COMMAND` | `npx -y @wonderwhy-er/desktop-commander` | Any stdio MCP server launch command |
| `WSDASH_CHAT_MODE` | `ask` | Default gate stage: `plan` \| `ask` \| `allow` \| `auto` \| `yolo` |
| `WSDASH_OMP_AUDIT_LOG` | *(auto-detected)* | Optional override for OMP harness audit log path |

`WSDASH_HOME` (env only) relocates all state from `~/.wsdash` — used by tests and
useful for a scratch profile.

## 2. `~/.wsdash/config.json` — dashboard

JSON object; keys merge over these defaults (unknown keys ignored; `weights` merges
per-signal):

```json
{
  "roots": ["~/sessions"],
  "max_depth": 2,
  "cache_ttl_seconds": 300,
  "incomplete_threshold": 10.0,
  "editor_workspace_globs": [
    "~/Library/Application Support/Code/User/workspaceStorage/*/workspace.json",
    "~/Library/Application Support/Cursor/User/workspaceStorage/*/workspace.json"
  ],
  "max_editor_workspaces": 50,
  "weights": {
    "diff_bytes": 0.25, "unmerged_branches": 0.15, "stale_worktrees": 0.10,
    "last_touch": 0.15, "failing_tests": 0.20, "todo_markers": 0.15
  },
  "launchd_label": "com.douglastalley.wsdash",
  "ignore_dirs": ["node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"]
}
```

Notes:

- **roots** — directories scanned (bounded by `max_depth`) for repos/worktrees and
  session dirs. Add project drives here, e.g. `"/Volumes/YourVolume/Development"`.
- **cache_ttl_seconds** — score cache expiration (the "5-minute cache").
- **incomplete_threshold** — score at which a workspace is surfaced INCOMPLETE.
- **weights** — per-signal; also applies to plugin providers by NAME (plugin's own
  `WEIGHT` is the fallback, then 0.1).
- After changing `roots`, run `wsdash scan` then `wsdash install` so the launchd
  watch set matches (doctor's `watch-set-current` check tells you when it doesn't).

A corrupt `config.json` is ignored (defaults used) — fix the JSON and rerun.

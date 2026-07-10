# Changelog

All notable changes to wsdash. Dates are America/New_York.

## [0.2.0-beta.1] — 2026-07-09

First feature-complete beta.

### Added
- **LLM Partner** (`wsdash chat`): terminal chat REPL + one-shot, OpenAI-compatible
  and Anthropic wire support via stdlib urllib, `.env.local` configuration with
  env-var precedence, configurable/replaceable system prompt.
- **MCP tool use**: stdio JSON-RPC client; Desktop Commander by default
  (`WSDASH_MCP_COMMAND` for any stdio server); built-in tools `get_recap`,
  `project_diff`, `workspace_scores`.
- **Gate stages** for tool execution: `plan` / `ask` / `allow` / `auto` / `yolo`
  over a read/write/dangerous classification; TTY confirmation prompts; fail-closed
  non-interactive confirms; 0600 transcripts with gate decisions logged.
- **Recap engine** (`wsdash recap`, `--ask`): scans Claude Code, Codex CLI/Desktop,
  floyd family (floyd/ff/superfloyd/…), and OMP (OhMyPi/OpenMythos) logs; resolves
  projects touched; per-project commits/shortstat/diffs; open items derived from the
  six dirtiness signals; instruction-blob and paste-noise title filtering.
- `wsdash mcp tools|call` debug driver; `wsdash --version`; `wsdash` PATH symlink.
- Beta docs: QUICKSTART, USER_MANUAL, CONFIGURATION, TROUBLESHOOTING, SECURITY,
  KNOWN_ISSUES, RELEASE_NOTES.

### Fixed (release QA pass, 9 issues)
- Chat transcripts were world-readable → 0600. (high)
- Memory ceiling breach (60–115 MB) on large repos/transcripts → streamed git I/O
  (`run_stream`), generator-based JSONL reading with seek-tail, >512 KB record skip,
  `--shortstat`, early text clipping → 48.8 MB worst-case peak. (high)
- Malformed numeric env values crashed chat → tolerant parse + warning.
- Codex titles showed AGENTS.md instruction blobs; Claude titles showed pasted
  terminal output → filtered.
- `$HOME`/volume roots treated as projects → excluded unless repos.
- Quiet floyd harnesses omitted from recap → always listed.
- `recap --hours` accepted negatives → clamped to [1, 336].
- `wsdash` not on PATH → `~/.local/bin` symlink; `bin/wsdash` now resolves the
  project root through symlinks (`realpath`).
- doctor's zero-idle check counted the user's own interactive REPL (has a TTY) as a
  stray process → only TTY-less background processes count.

### Verification
- 36 automated tests (unit + integration: six signals byte-exact, TTL, plugins,
  corruption recovery, both LLM wires, gate matrix, MCP stub round-trip, scanners,
  chat loop). Live checks covered launchd filesystem events, git hooks, and the
  configured MCP integration.

## [0.1.0] — 2026-07-09

Initial build: six-signal dirtiness scoring (unstaged diff bytes, unmerged branches,
stale worktrees, hours since touch, failing-test records, new TODO markers), 5-minute
score cache, launchd WatchPaths + git-hook event-driven recompute (no daemons, no
polling), terminal table/detail views, lazy suggest layer, pluggable providers/views,
atomic/quarantining state store, doctor health checks, zero-idle and <50 MB memory
guarantees.

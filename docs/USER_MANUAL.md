# wsdash User Manual (0.2.0-beta.1)

macOS-native, event-driven, zero-idle workspace dirtiness dashboard with an LLM
Partner. Python 3.11+ stdlib only. This manual documents the behavior verified in
the 2026-07-09 release QA pass (36 automated tests + live dogfood).

## Contents

1. [Concepts](#1-concepts)
2. [Commands](#2-commands)
3. [Dirtiness scoring](#3-dirtiness-scoring)
4. [Event-driven updates](#4-event-driven-updates)
5. [LLM Partner chat](#5-llm-partner-chat)
6. [Gate stages](#6-gate-stages)
7. [Recap: where did I leave off](#7-recap)
8. [Plugins: providers and views](#8-plugins)
9. [State on disk](#9-state-on-disk)
10. [Exit codes](#10-exit-codes)

---

## 1. Concepts

- **Workspace** — a git repo, a linked git worktree, a plain session directory under
  a configured root, or an editor workspace folder (VS Code / Cursor
  `workspaceStorage`). Discovered by `wsdash scan`, tracked in a registry.
- **Dirtiness score** — 0–100 from six measurable signals (§3). Score ≥ threshold
  (default 10) marks the workspace **INCOMPLETE** and surfaces it at the top.
- **Zero idle** — every command renders and exits. Between invocations there are no
  wsdash processes. Recomputation is event-driven (§4), never polled.
- **LLM Partner** — a chat interface (`wsdash chat`) with gated tool access to your
  machine via MCP (Desktop Commander) plus built-in recap tools (§5–7).

## 2. Commands

```
wsdash [--version] [--mem] [--json] <command>
```

| Command | What it does |
|---|---|
| `wsdash` / `wsdash view` | Render the dashboard table and exit. `--view detail <path>` for one workspace's signal breakdown; `--view <name>` for plugin views. |
| `wsdash scan` | Discover workspaces under the configured roots + editor workspaces into the registry. |
| `wsdash score [path] [--force]` | Print scores; `--force` bypasses the 5-minute cache. |
| `wsdash suggest` | Predictive layer (lazy-loaded): suggests relevant workspaces from branch-token overlap, event co-activity clusters, and local dependency links (`package.json file:`, `requirements -e`, `go.mod replace`). |
| `wsdash install` | Write + bootstrap the launchd WatchPaths agent and install chain-safe git hooks in every registered repo. Idempotent; also the fix for watch-set drift. |
| `wsdash uninstall` | Bootout + remove the agent; remove our git hooks, restoring any chained originals. |
| `wsdash doctor [--repair]` | 10 health checks (python, git, state, registry, cache integrity, plist, agent loaded, watch-set sync, zero-idle, memory ceiling). `--repair` purges quarantined files and rebuilds the registry. |
| `wsdash providers` / `wsdash views` | List registered signal providers / views with source (builtin/user) and gate class. |
| `wsdash chat [-m MSG] [--mode M] [--no-mcp]` | LLM Partner REPL, or one-shot with `-m`. |
| `wsdash recap [--hours N] [--ask Q]` | Harness-log scan (§7); `--ask` routes the question through the Partner. |
| `wsdash mcp tools` / `wsdash mcp call <tool> '<json>'` | Direct MCP driver for debugging. **Ungated** — equivalent to running the server by hand; the gated path is chat. |
| `wsdash hook fs` / `wsdash hook git <path>` | Event entrypoints. Called by launchd and git hooks; you normally never run these. |

Global flags: `--json` machine-readable output where supported; `--mem` prints
`peak_rss_mb=…` to stderr at exit.

## 3. Dirtiness scoring

`score = 100 × Σ(weightᵢ × normalizedᵢ) / Σ weightᵢ` over applicable, non-erroring signals.

| Signal | Measures | Saturates at | Weight |
|---|---|---|---|
| `diff_bytes` | unstaged diff size in bytes (streamed count — flat memory on any repo size) | 50,000 B | 0.25 |
| `unmerged_branches` | local branches not merged into the default branch | 5 | 0.15 |
| `stale_worktrees` | prunable / path-missing linked worktrees | 3 | 0.10 |
| `last_touch` | hours since newest mtime (workspace root, immediate entries, `.git/index|HEAD`) | 168 h | 0.15 |
| `failing_tests` | recorded failures: pytest `.pytest_cache/v/cache/lastfailed` + `.wsdash-tests.json {"failing": N}` — never runs your tests | 10 | 0.20 |
| `todo_markers` | new TODO/FIXME/HACK/XXX in the unstaged diff + untracked files (≤100 files, ≤256 KB each) | 10 | 0.15 |

Scores cache in `~/.wsdash/state/score-<id>.json` with a **300-second TTL**. Reads
within the TTL are served from cache; events force targeted recomputes. Weights and
threshold are configurable (see [CONFIGURATION.md](CONFIGURATION.md)).

A workspace whose path vanishes (unplugged volume) becomes status `disconnected`:
its last score is retained, nothing crashes, and it recovers automatically when the
path returns.

## 4. Event-driven updates

Never polls. Three recompute triggers only:

1. **launchd WatchPaths** (fsevents-backed) on the roots, each workspace dir, and
   each repo's `.git` dir → spawns a short-lived `wsdash hook fs`, which recomputes
   only workspaces whose content is newer than their cached score.
2. **git hooks** (`post-commit`, `post-checkout`, `post-merge`, `post-index-change`)
   → `wsdash hook git "$PWD"` recomputes exactly that workspace. Pre-existing hooks
   are preserved: they're moved to `<name>.pre-wsdash` and chained.
3. **On-demand TTL** — an invocation that finds a cache older than 5 minutes
   recomputes it.

WatchPaths is shallow (top-level entries only); deep file edits are still caught by
the `.git` watch on any git operation, by the hooks, and by the TTL. When the
workspace set changes, a drift marker is set; `wsdash doctor` reports it and
`wsdash install` resyncs (we never reload launchd from inside a launchd job).

## 5. LLM Partner chat

`wsdash chat` starts a REPL; `wsdash chat -m "…"` runs one turn and exits.

- **Providers**: `openai` (any `/chat/completions`-compatible endpoint, including
  local proxies — keyless works) or `anthropic` (`/v1/messages`). Configured via
  `.env.local` (see [CONFIGURATION.md](CONFIGURATION.md)).
- **Tools**: Desktop Commander via MCP stdio (26 tools at 0.2.43: read_file,
  search_code, write_file, edit_block, start_process, …) plus built-ins
  `get_recap`, `project_diff`, `workspace_scores`. `--no-mcp` for chat without
  Desktop Commander. A dead/unspawnable MCP server degrades chat gracefully —
  built-ins still work and the banner shows why.
- **System prompt**: default partner prompt; replace wholesale with
  `~/.wsdash/prompts/partner.md` (or `WSDASH_LLM_SYSTEM_PROMPT_FILE`); append inline
  text with `WSDASH_LLM_SYSTEM_PROMPT`.
- **REPL commands**: `/mode <m>`, `/tools` (with gate class per tool), `/recap`,
  `/clear` (reset history), `/quit`.
- **Transcripts**: every turn and gate decision appends to
  `~/.wsdash/chat/session-<ts>.jsonl`, mode 0600.
- **Bounds**: max 20 tool rounds per turn; tool results truncated at 60 KB;
  HTTP retries once on 5xx/network errors.

## 6. Gate stages

Every tool call is classified `read`, `write`, or `dangerous`
(process/config-mutating: `start_process`, `interact_with_process`, `kill_process`,
`force_terminate`, `set_config_value`, …). Unknown tools default to `write` unless
their name matches a read prefix (`read_`, `list_`, `get_`, `search_`, `find_`).

| Mode | read | write | dangerous |
|---|---|---|---|
| `plan` | blocked (narrated) | blocked | blocked |
| `ask` (default) | confirm | confirm | confirm |
| `allow` | auto | confirm | confirm |
| `auto` | auto | auto | confirm |
| `yolo` | auto | auto | auto |

Confirmations prompt on your TTY: `⚠ allow tool 'write_file' with {…} ? [y/N]`.
**Non-interactive sessions fail closed**: a `confirm` with no TTY is a deny. Plan
mode returns a notice instructing the model to describe, not retry. Denied calls
return a notice instructing the model not to retry verbatim.

Set the default mode with `WSDASH_CHAT_MODE`; switch live with `/mode`.

## 7. Recap

`wsdash recap` answers "where did I leave off?" from local evidence:

| Harness | Source | Notes |
|---|---|---|
| Claude Code | `~/.claude/projects/<proj>/*.jsonl` | CLI/desktop/web sessions that touched this machine; summary records used as titles |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `originator` distinguishes Codex Desktop vs CLI (`codex-tui`, `codex_exec`) |
| floyd family | every `~/.floyd*/floyd.db` (sqlite, read-only) | floyd (OhMyFloyd), ff, superfloyd, forks — always listed, 0 sessions when quiet |
| OMP | `~/.omp/agent/agent.db` threads + harness audit log | OhMyPi / OpenMythos runtimes; `source_kind` distinguishes origin |

`wsdash recap` uses `WSDASH_OMP_AUDIT_LOG` when set, otherwise auto-detects known OMP
audit log locations.

Output: per-harness sessions in the window (default 24 h, clamp 1–336), the projects
those sessions touched, per-project git activity (commits, `--shortstat`, changed-file
count), and **open items** derived from the six signals. Harness-injected
instruction blobs (AGENTS.md dumps) and terminal-paste noise are filtered from titles.

`wsdash recap --ask "…"` or any natural-language question in chat routes through the
Partner, which chains `get_recap` → `project_diff` per project and returns ranked
priorities. All scanners are defensive: missing dirs → harness reported unavailable;
per-file/per-row parse errors are contained; oversized transcripts are read
head+tail with bounded memory.

## 8. Plugins

Drop a `.py` file — no core changes, broken plugins are isolated (load errors
reported; collect errors become error-signals excluded from the score).

**Signal provider** (`~/.wsdash/providers/*.py`):

```python
NAME, UNIT, WEIGHT = "file_count", "files", 0.05
def applies_to(ws): return True          # ws: {id, path, name, kind, repo_root, ...}
def collect(ws):
    import os
    n = len(os.listdir(ws["path"]))
    return {"value": n, "normalized": min(n / 100, 1.0), "detail": f"{n} entries"}
```

**View** (`~/.wsdash/views/*.py`):

```python
NAME = "count"
def render(model):                        # model: {workspaces, config, color, generated_at}
    return f"{len(model['workspaces'])} workspaces"
```

Weight overrides: `"weights": {"file_count": 0.1}` in `~/.wsdash/config.json`.
Verify registration with `wsdash providers` / `wsdash views`.

## 9. State on disk

```
~/.wsdash/                     (override with WSDASH_HOME — used by the test suite)
  config.json                  dashboard config overrides
  .env.local                   LLM Partner config (0600)
  state/registry.json          workspace registry (incrementally synced)
  state/score-<id>.json        per-workspace score cache (5-min TTL)
  log/events.jsonl             event telemetry (size-capped at 512 KB)
  log/launchd.log              launchd job output
  chat/session-<ts>.jsonl      chat transcripts (0600)
  prompts/partner.md           optional system-prompt override
  providers/  views/           plugins
~/Library/LaunchAgents/com.douglastalley.wsdash.plist
```

All state writes are atomic (tmp + rename); corrupt files are quarantined
(`*.corrupt-<ts>`) and rebuilt; a bounded flock serializes concurrent events.

## 10. Exit codes

| Command | 0 | non-zero |
|---|---|---|
| `doctor` | all checks OK | 1: at least one check failed |
| `install` | agent loaded | 1: bootstrap failed |
| `view` | rendered | 2: unknown view name |
| `chat -m` / `recap --ask` | answered | 1: LLM/config error (message on stderr) |
| `mcp` | ok | 1: MCP error, 2: usage |

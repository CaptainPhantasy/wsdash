# wsdash
macOS-native, event-driven, zero-idle workspace dirtiness dashboard.
Python 3.11+ stdlib only. No dependencies, no daemons, no polling.

**Version 0.2.0-beta.1** (runtime: `0.2.0b1`) — docs: [Quick Start](docs/QUICKSTART.md) ·
[User Manual](docs/USER_MANUAL.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Configuration](docs/CONFIGURATION.md) ·
[Troubleshooting](docs/TROUBLESHOOTING.md) · [Security](docs/SECURITY.md) ·
[Known Issues](KNOWN_ISSUES.md) · [Release Notes](RELEASE_NOTES.md) ·
[Changelog](CHANGELOG.md)

## What it does

Tracks git repos/worktrees, shell session directories (under configured roots,
default `~/sessions`), and editor workspace directories (VS Code / Cursor
`workspaceStorage`), scores each 0–100 for "dirtiness", and surfaces workspaces
that look incomplete.

## Six-signal dirtiness score

| Signal | Measure | Saturates at | Default weight |
|---|---|---|---|
| `diff_bytes` | unstaged diff size in bytes | 50 000 B | 0.25 |
| `unmerged_branches` | local branches not merged into default branch | 5 | 0.15 |
| `stale_worktrees` | prunable / path-missing linked worktrees | 3 | 0.10 |
| `last_touch` | hours since newest mtime (root, entries, .git/index|HEAD) | 168 h | 0.15 |
| `failing_tests` | pytest `lastfailed` + `.wsdash-tests.json {"failing": N}` | 10 | 0.20 |
| `todo_markers` | new TODO/FIXME/HACK/XXX in unstaged diff + untracked files | 10 | 0.15 |

`score = 100 * Σ(wᵢ·normᵢ) / Σwᵢ` over applicable, non-erroring providers.
Scores are cached in `~/.wsdash/state/score-<id>.json` with a **5-minute TTL**.
`score >= incomplete_threshold` (default 10) ⇒ surfaced as INCOMPLETE.

## Execution model — the guarantees

- **On-demand only.** Every command renders and exits. There is no resident mode,
  no daemon, no timer. Between invocations the footprint is zero processes.
- **Never polls.** Recomputation happens only when (a) launchd fires a
  WatchPaths (fsevents-backed) event on a root / workspace / `.git` dir,
  (b) a git hook (`post-commit`, `post-checkout`, `post-merge`,
  `post-index-change`) fires, or (c) an invocation finds a cache expired.
- **Incremental.** Event handling recomputes only workspaces whose content is
  newer than their cached score; git hooks recompute exactly one workspace.
- **Memory ceiling 50 MB.** Lazy per-subcommand imports; measured peak RSS
  ~19 MB. `wsdash doctor` enforces the check; `--mem` prints peak RSS.
- **Fault tolerant.** Atomic tmp+rename writes (interruption-safe), corrupt
  state auto-quarantined and recomputed, bounded flock for concurrent events,
  vanished paths kept as `disconnected` instead of dropped,
  `wsdash doctor --repair` rebuilds the registry.

launchd itself is the orchestrator: the agent plist has `RunAtLoad=false` and
spawns a short-lived `wsdash hook fs` process only when a watched path changes.
WatchPaths is shallow, so deep edits are covered by the `.git`-dir watch + git
hooks + TTL fallback. When the workspace set changes, a drift marker is set and
`wsdash doctor` tells you to re-run `wsdash install` (we never reload launchd
from inside a launchd job).

## Commands

```
wsdash                  # dashboard (table view), then exit
wsdash scan             # discover workspaces into the registry
wsdash view --view detail [path]
wsdash score [path] [--force]
wsdash suggest          # predictive layer — imported only on invocation
wsdash install          # launchd agent + git hooks (idempotent)
wsdash uninstall        # remove agent + restore chained hooks
wsdash doctor [--repair]
wsdash providers | views
wsdash --json ... | wsdash --mem ...
```

## Predictive context awareness (lazy)

`wsdash suggest` analyzes, at invocation time only:
1. branch dependencies (shared branch/name tokens across workspaces),
2. recent activity clusters (event co-occurrence within 30-min windows),
3. project interdependencies (`package.json` file:/link:, `requirements*.txt -e`,
   `go.mod replace` local paths),
and ranks workspaces you likely need next, with reasons.

## Pluggable providers and views

Drop a `.py` file in `~/.wsdash/providers/` or `~/.wsdash/views/` — no core changes.

```python
# ~/.wsdash/providers/file_count.py
import os
NAME, UNIT, WEIGHT = "file_count", "files", 0.05
def applies_to(ws): return True
def collect(ws):
    n = len(os.listdir(ws["path"]))
    return {"value": n, "normalized": min(n / 100, 1.0), "detail": f"{n} entries"}
```

```python
# ~/.wsdash/views/count.py
NAME = "count"
def render(model): return f"{len(model['workspaces'])} workspaces"
```

Weights are overridable per-signal in `~/.wsdash/config.json` (`"weights"`).
Broken plugins are isolated: load errors are reported, collect errors become
error signals excluded from the score. Nothing a plugin does can crash the core.

## State layout

```
~/.wsdash/                 (override with WSDASH_HOME)
  config.json              user config overrides
  state/registry.json      workspace registry (incrementally synced)
  state/score-<id>.json    per-workspace score cache (5-min TTL)
  log/events.jsonl         append-only event telemetry (size-capped)
  log/launchd.log          launchd job output
  providers/ views/        user plugins
```

## LLM Partner (`wsdash chat` / `wsdash recap`)

A full chat interface in the terminal, wired to your machine.

- **Config**: `.env.local` (`~/.wsdash/.env.local` global, `./.env.local` per-project,
  real env wins; see `.env.local.example`). OpenAI-compatible or Anthropic wire with
  API key; works keyless against local proxies. Malformed values fall back with a warning.
- **Internally promptable**: default partner prompt + `~/.wsdash/prompts/partner.md`
  full override + `WSDASH_LLM_SYSTEM_PROMPT` inline additions.
- **Tools via MCP**: Desktop Commander by default (`WSDASH_MCP_COMMAND` for any stdio
  MCP server) — read/search/write/edit files, run/inspect processes — plus built-ins
  `get_recap`, `project_diff`, `workspace_scores`.
- **Gate stages** (`--mode` or `/mode`): `plan` (propose only, nothing executes),
  `ask` (confirm every call), `allow` (non-destructive auto, writes confirm),
  `auto` (read+write auto, dangerous confirm), `yolo` (everything auto). Non-TTY
  confirmation fails closed. Every call is classified read/write/dangerous and
  logged to a 0600 transcript in `~/.wsdash/chat/`.
- **Where did I leave off?** Ask in natural language (`wsdash chat`, or
  `wsdash recap --ask "..."`), or get the raw scan with `wsdash recap`. Scans
  Claude Code (`~/.claude/projects`), Codex CLI/Desktop (`~/.codex/sessions`,
  originator distinguishes desktop), the floyd family (every `~/.floyd*/floyd.db`:
  floyd/ff/superfloyd/…), and OMP/OhMyPi/OpenMythos (`~/.omp/agent/agent.db` +
  harness audit log). Resolves the projects touched, shows per-project commits and
  diffs (`project_diff`), and derives open items from the six dirtiness signals so
  you can prioritize what to pick up first.
- **Hardened**: memory-flat streaming for giant diffs/transcripts (48.8 MB peak on a
  pathological corpus, doctor-gated 50 MB ceiling), tolerant config parsing, bounded
  tool loops (20 rounds), dead-MCP-server detection, per-line log-parse error
  containment, and disconnected-volume tolerance. Release QA covered 10 issues found
  and fixed before the beta.
- **Debug**: `wsdash mcp tools` / `wsdash mcp call <tool> '<json>'` (ungated driver,
  equivalent to running the server by hand).

## Tests

```
python3.11 -m unittest discover -s tests -v   # 36 tests
```

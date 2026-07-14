# wsdash Architecture (0.2.0-beta.1)

The modification map: what lives where, what depends on what, which invariants must
survive your edit, and step-by-step recipes for the common feature additions.
Generated from the actual tree on 2026-07-09 (3,334 LOC incl. tests).

## 1. Layer diagram

```
                    ┌─────────────────────────────────────────────┐
  entrypoints       │  bin/wsdash (realpath shim) · __main__.py   │
                    └──────────────────┬──────────────────────────┘
                                       ▼
  dispatch          ┌─────────────────────────────────────────────┐
                    │  cli.py — argparse, one branch per command, │
                    │  LAZY imports inside each branch            │
                    └──┬───────────┬──────────────┬───────────────┘
                       ▼           ▼              ▼
  dashboard      ┌──────────┐ ┌──────────┐ ┌────────────────────────────┐
  domain         │ scoring  │ │ events   │ │ llm/ (Partner subpackage)  │
                 │ suggest  │ │ installer│ │  chat ── client (HTTP)     │
                 │ doctor   │ │          │ │   │  └─ mcpclient (stdio)  │
                 └────┬─────┘ └────┬─────┘ │   ├─ gates  ├─ toolkit     │
                      ▼            ▼       │   ├─ prompts└─ recap ──────┼──┐
  plugin surfaces ┌─────────────────────┐  │   └─ envfile               │  │
                  │ providers/ (6+user) │◄─┼───────────────────────────-┘  │ (recap reuses
                  │ views/     (2+user) │  └────────────────────────────┘  │  providers via
                  └──────────┬──────────┘                                  │  scoring)
                             ▼                                            │
  foundation      ┌────────────────────────────────────────────┐          │
                  │ config.py · store.py · gitutil.py ·        │◄─────────┘
                  │ discover.py                                │
                  └────────────────────────────────────────────┘
```

**Dependency rule (enforced by convention, keep it):** arrows only point downward.
Foundation imports nothing above it; providers/views import only foundation
(`gitutil`, `config`); domain imports foundation + plugin registries; `llm/` imports
domain + foundation via `..`; only `cli.py` imports everything — and only inside the
command branch that needs it (the lazy-import pattern is the memory ceiling's main
defense; never hoist those imports to module level).

## 2. Module map

### Foundation

| Module | LOC | Responsibility | Touch it when… |
|---|---|---|---|
| `config.py` | 64 | `DEFAULTS` dict, `home()` (`WSDASH_HOME` override), `load()`/`save()` merge of `~/.wsdash/config.json`, `roots()` | adding a config key: add to `DEFAULTS`, document in CONFIGURATION.md |
| `store.py` | 152 | ALL state I/O: `atomic_write_json` (tmp+rename), `load_json` (corruption → quarantine `*.corrupt-<ts>` + default), `locked()` bounded flock, registry load/save, `score_path`/`is_fresh` (TTL), `ws_id` (sha1[:12] of realpath), `append_event`/`read_events` (512 KB-capped jsonl) | any new persistent state — never open state files directly elsewhere |
| `gitutil.py` | 75 | subprocess git: `run()` (captured, timeout), `run_stream()` (chunked, line-callback, **flat memory** — use for anything that can be huge), `is_repo`, `common_dir`, `default_branch` | any new git query. If output can exceed ~1 MB, you MUST use `run_stream` |
| `discover.py` | 127 | workspace discovery: root walk (`max_depth`, `ignore_dirs`) → repos + `git worktree list` linked worktrees + depth-0 session dirs; editor `workspaceStorage` globs; `sync_registry()` incremental merge (vanished ⇒ `missing=True`, never dropped); `register_adhoc()` for hook-discovered paths | adding a workspace source (new editor, tmux sessions, …): add a finder, call `add()` in `find_workspaces` |

### Dashboard domain

| Module | LOC | Responsibility | Touch it when… |
|---|---|---|---|
| `scoring.py` | 55 | `compute_score(ws)` = 100·Σ(w·norm)/Σw over applicable non-erroring providers; `get_score()` cache-or-compute (TTL 300 s); disconnected handling (keeps last score, status `disconnected`) | changing score semantics. Signal changes belong in providers, not here |
| `events.py` | 66 | `handle_fs()` (registry re-sync + mtime-gated targeted recompute + drift-marker check) and `handle_git(path)` (single-workspace recompute). Both run under `store.locked()`, log to events.jsonl, and EXIT | changing what an event recomputes. Never reload launchd from here (would kill our own process tree — that's what the drift marker is for) |
| `installer.py` | 163 | launchd plist build (`WatchPaths` = roots + ws dirs + `.git` common dirs; `ProgramArguments` = [sys.executable, bin, hook, fs]; `RunAtLoad=False`), bootstrap/bootout; chain-safe git hooks (`post-commit/checkout/merge/index-change`, marker `# wsdash-managed-hook v1`, pre-existing hook → `<name>.pre-wsdash`, exec-chained) | watching new paths, adding a hook type, changing the label |
| `suggest.py` | 120 | lazy predictive layer: branch-token overlap, event co-activity windows (30 min), local dep links (package.json `file:`/`link:`, requirements `-e`, go.mod `replace`) → ranked suggestions | adding a suggestion heuristic: append a `reasons[]` producer, keep it deterministic |
| `doctor.py` | 93 | 10 health checks (each `{check, ok, detail}`), `peak_rss_mb` (macOS: ru_maxrss is BYTES), TTY-aware `idle_processes` (TTY-attached = user's REPL, not stray), `repair()` | adding a check: append in `run_checks`; doctor exit code = all(ok) |

### Plugin surfaces (stable contracts — extend, don't edit)

| Module | Contract |
|---|---|
| `providers/__init__.py` | loads `BUILTIN` list + `~/.wsdash/providers/*.py` (sorted, isolated: import errors → `errors[]`, collect errors → error-signal excluded from score). Module contract: `NAME`, `UNIT`, `WEIGHT`, `applies_to(ws)→bool`, `collect(ws)→{value, normalized 0..1, detail}` |
| six builtins | `diff_bytes` (streamed byte count, cap 50 kB), `unmerged_branches` (cap 5), `stale_worktrees` (repo-kind only, cap 3), `last_touch` (all kinds, cap 168 h; also exports `newest_mtime` used by `events.handle_fs`), `failing_tests` (pytest lastfailed + `.wsdash-tests.json`, cap 10), `todo_markers` (streamed diff -U0 + ≤100 untracked ≤256 kB, cap 10) |
| `views/__init__.py` | loads `table` + `detail` + `~/.wsdash/views/*.py`. Contract: `NAME`, `render(model)→str`; `model = {workspaces:[score docs], config, color, generated_at}` |

### LLM Partner (`wsdash/llm/`)

| Module | LOC | Responsibility | Touch it when… |
|---|---|---|---|
| `envfile.py` | 100 | `.env.local` parse + precedence (env > cwd file > global file), `llm_config()` (tolerant `_num` parsing, key fallbacks OPENAI/ANTHROPIC_API_KEY), `mask()` | new config key: add to `KNOWN_KEYS` + `llm_config()` + CONFIGURATION.md |
| `client.py` | 164 | **pure** `build_request()` / `parse_response()` per wire (openai `/chat/completions`, anthropic `/v1/messages`) + `LLMClient.chat()` (urllib, 1 retry on 5xx/network, key never in errors). Canonical message + tool-spec formats defined in its docstring — everything above speaks canonical, only this module speaks wire | adding a provider wire (see recipe §5.4) |
| `mcpclient.py` | 133 | MCP stdio ndjson JSON-RPC: reader thread → queue (every wait timeout-bounded), initialize handshake (protocol `2024-11-05`), `tool_specs()` (inputSchema→input_schema), `call_tool()` (content blocks → text, `isError` → `TOOL ERROR:`), dead-server detection | MCP protocol changes; supporting HTTP-transport MCP would be a sibling class |
| `gates.py` | 63 | classification (`READ_TOOLS`/`DANGEROUS_TOOLS` pinned sets + read-prefix heuristic, unknown ⇒ write) and `decide(mode, tool) → allow/confirm/deny-plan`; the mode×class matrix in its docstring is normative | reclassifying a tool, adding a mode (also update chat `--mode` choices in cli.py + docs + `GateTests.test_decision_matrix`) |
| `toolkit.py` | 54 | built-in tool specs (`get_recap`, `project_diff`, `workspace_scores` — all read-class) + `call_builtin()` | adding a built-in tool (recipe §5.5) |
| `chat.py` | 177 | `ChatSession`: tool loop (≤20 rounds), gate enforcement (`_execute`: deny-plan / confirm via `confirm_fn` — TTY prompt, **non-TTY ⇒ deny**), builtin-vs-MCP dispatch, 0600 transcript, `one_shot()`, `repl()` (/mode /tools /recap /clear /quit). Injectable `client` + `confirm_fn` = how tests script it | REPL commands, loop policy. Tool results clip at 60 kB |
| `prompts.py` | 45 | default partner prompt; override file + inline-append resolution | changing default Partner behavior |
| `recap.py` | 441 (largest) | per-harness scanners (`scan_claude`, `scan_codex`, `scan_floyd_family`, `scan_omp`) each → `{name, available, sessions[], notes[]}`; memory-bounded readers (`_iter_jsonl` generator: >8 MB files → head 200 + seek 2 MB tail; >512 kB lines skipped; `_tail_lines`); noise filters (`_is_instruction_blob`, `_title_from`); `git_activity` (shortstat + streamed porcelain count), `open_items` (reuses providers via scoring), `project_diff` (capped streaming capture), `scan()` (hours clamp 1–336, `_is_project_path` root filter), `render()` | adding a harness scanner (recipe §5.3). EVERY reader here must stay bounded — this file caused the 115 MB ceiling breach three times |

### Entry/dispatch

| Module | Notes |
|---|---|
| `bin/wsdash` | `#!/usr/bin/env python3`, sys.path from `realpath(__file__)` (symlink-safe — do not revert to abspath) |
| `cli.py` | one `elif cmd ==` branch per command. Pattern for new commands: add subparser, add branch, import inside the branch. `_load_docs()` implements lazy loading (fresh cache ⇒ no provider import at all) |

## 3. Data flow (the four paths that matter)

**View (on-demand):** `cli view` → registry → per-ws cached score if `is_fresh(ttl=300)` else `scoring.get_score` (loads providers on first miss only) → `views[name].render(model)` → print → **exit**.

**Event (fs):** file/git change → launchd WatchPaths → spawns `hook fs` → `events.handle_fs` under flock → `sync_registry` → for each ws: recompute **only if** `newest_mtime(ws) > cached.computed_at` → atomic write score → append event → drift check → **exit**. (git hook path: `handle_git` recomputes exactly one ws.)

**Chat turn:** user text → `client.chat(messages, tools)` → wire build → HTTP → parse → if `tool_calls`: per call `gates.decide(mode, name)` → deny-plan notice / confirm (TTY y/N, non-TTY deny) / execute (`toolkit.call_builtin` or `mcp.call_tool`) → append `role:tool` results → loop (≤20) → final text. Every step transcripted.

**Recap:** `scan()` → 4 scanner families (bounded readers) → collect session `project` cwds → `_is_project_path` filter → per project `git_activity` + `open_items` (signal providers on an ad-hoc ws dict) → doc → `render()` or fed to the Partner via `get_recap` tool.

## 4. On-disk schemas (all under `~/.wsdash`, all atomic writes)

```jsonc
// state/registry.json
{"version":1, "updated_at":ts, "workspaces": {"<12-hex>": {
  "id","path","name","kind":"repo|worktree|session-dir","repo_root",
  "sources":["scan"|"editor"|"hook"], "first_seen":ts, "missing":bool }}}

// state/score-<id>.json (TTL vs computed_at)
{"version":1,"id","path","name","kind","computed_at":ts,"score":0-100,
 "status":"ok|incomplete|disconnected",
 "signals":[{"name","unit","value","normalized":0-1,"weight","detail","error"}]}

// log/events.jsonl (capped 512KB→tail 400)   {"ts","kind":"fs|git","ws","path",...}
// chat/session-<ts>.jsonl (0600)  {"ts", role/content | event:"tool"/"gate" records}
```

Schema changes: bump `"version"`, make `load_json` consumers tolerate the old shape
(quarantine-and-recompute already covers you if you don't).

## 5. Recipes

### 5.1 New dirtiness signal
1. Create `wsdash/providers/<your_signal>.py` (or `~/.wsdash/providers/` for personal-only,
   zero code changes): `NAME/UNIT/WEIGHT/applies_to/collect` (§2 contract). Use
   `gitutil.run_stream` if output can be big; raise on failure (isolation handles it).
2. Builtin only: append name to `providers/__init__.BUILTIN` and a default weight in
   `config.DEFAULTS["weights"]`.
3. If it's read-classified for the Partner's benefit, the `get_`/`read_` prefix rule
   in `gates.py` usually covers it; pin it in `READ_TOOLS` only if exposed as a tool.
4. Test: extend the fixture in `tests/test_wsdash.py:make_fixture_repo` with the dirt
   condition + assert in `test_02_six_signals` style. Docs: USER_MANUAL §3 table.

### 5.2 New view
`~/.wsdash/views/name.py` or builtin (`views/BUILTIN`): `NAME` + `render(model)`.
Respect `model["color"]`. Wide output must fit a terminal; sort by score desc.

### 5.3 New harness scanner (recap)
1. In `llm/recap.py`, add `scan_<harness>(since, now) → {name, available, sessions[], notes[]}`
   (session dict fields: `id, origin, project, title, started, ended, n_user_msgs,
   last_user, last_assistant` — empty strings/0 are fine).
2. **Bounded reads only**: `_iter_jsonl`/`_tail_lines` for files, `mode=ro` URIs for
   sqlite, clip texts to 4 kB before storing, wrap parse errors per row.
3. Titles through `_title_from`, harness-injected text through `_is_instruction_blob`.
4. Register in `scan()`'s harness list. Test with a fixture like `RecapTests`
   (fake `HOME` monkeypatch pattern). Re-measure: `wsdash --mem recap --hours 24`
   must stay < 50 MB.

### 5.4 New LLM provider wire
All in `llm/client.py`: extend `build_request` + `parse_response` with a new
`provider ==` branch translating the canonical formats (docstring at top of file);
allow the value in `LLMClient.__init__`; add build/parse unit tests mirroring
`WireTests`; document in CONFIGURATION.md. Nothing above client.py changes.

### 5.5 New built-in Partner tool
1. Spec in `toolkit.BUILTIN_SPECS` (name, description the model will read, JSON schema).
2. Implementation branch in `call_builtin` (return a string; errors as `ERROR: …`).
3. Gate class: read-only tools go in `gates.READ_TOOLS`; anything mutating should NOT
   be in that set (falls to write ⇒ confirm in ask/allow).
4. Test via the `FakeClient` pattern in `ChatLoopTests` (scripted tool_calls, no network).

### 5.6 New CLI command
Subparser + `elif` branch in `cli.py` with imports **inside the branch**; add to
USER_MANUAL command table; smoke it in the doc-verification loop
(`wsdash <cmd> -h`); exit codes per §10 of the manual.

### 5.7 Different MCP server
No code: set `WSDASH_MCP_COMMAND` in `.env.local`. Tool classification for its tools
comes from prefix heuristics; pin exceptions in `gates.READ_TOOLS`/`DANGEROUS_TOOLS`.

## 6. Invariants — do not break these (and what guards them)

| Invariant | Why | Guard |
|---|---|---|
| No resident process; every command exits | product definition | doctor `zero-idle` (TTY-aware); launchd `RunAtLoad=False` |
| No polling loops anywhere (only bounded lock retry) | product definition | code review; events are launchd/git-hook driven + TTL-on-invocation |
| Peak RSS < 50 MB on any command | daily-tool guarantee | doctor `memory-ceiling`; `--mem`; streaming rules (`run_stream`, `_iter_jsonl`) — this broke 3× during QA, always via an unbounded read |
| Lazy imports per CLI branch | memory + startup | keep imports inside `elif` branches |
| State writes atomic + corruption self-heals | crash tolerance | `store.atomic_write_json`/`load_json` only; tests 05 |
| Vanished paths ⇒ `disconnected`, never dropped/crash | unplugged volumes are normal here | `discover.sync_registry`, `scoring.compute_score`; test 04; observed live both directions |
| Non-TTY confirm ⇒ deny (fail closed) | gate integrity for scripts/cron | `chat._tty_confirm`; `ChatLoopTests` |
| API key never in logs/errors | secret hygiene | `WireTests.test_key_never_in_errors` |
| Plugins can't crash the core | pluggability promise | provider/view loader isolation; tests 06–08 |
| Never launchctl-reload from inside a hook job | would kill our own process tree | drift marker + `wsdash install` flow |
| Canonical LLM formats above `client.py` | provider portability | wire logic confined to client.py |

## 7. Test map (36 tests)

| Suite | Covers |
|---|---|
| `tests/test_wsdash.py` (14) | discovery, six signals byte-exact vs fixture repo, score+TTL, disconnection, cache corruption recovery, provider/view plugins + broken-plugin isolation, table render, git-hook targeted recompute, plist build, suggest interdeps |
| `tests/test_llm.py` (22) | envfile parse/precedence/malformed-numbers/mask, both wire builds + parses, key-not-in-errors, gate classification + full decision matrix, MCP stub handshake/list/call/real-write/dead-server, recap fixtures (claude jsonl, floyd sqlite) + noise filters + path filters + project_diff bounds, chat loop auto/deny/plan/transcript via FakeClient |
| `tests/stub_mcp_server.py` | deterministic MCP server (echo + write_probe) — extend it when testing new MCP behaviors |

Run: `python3.11 -m unittest discover -s tests`. Everything uses a throwaway
`WSDASH_HOME` (set before imports — keep that ordering if you add test files).

## 8. Gotchas (paid for in QA, remember them)

- **macOS `ru_maxrss` is bytes** (Linux: KB) — `doctor.peak_rss_mb` handles it.
- **floyd sqlite**: `sessions.updated_at` is SECONDS, `messages.created_at` is MS —
  `recap._norm_ts` normalizes by magnitude (>1e12 ⇒ ms).
- **Codex rollouts** can contain multi-MB single-line JSON records — hence the 512 kB
  line skip and bounded head/tail reading.
- **launchd WatchPaths is shallow**; the `.git`-dir watch is what makes git ops feel
  instant. Deep non-git edits wait for the TTL.
- **`bin/wsdash` must use `realpath`** — the PATH symlink broke once on `abspath`.
- **Prompt glyphs in terminal scrollback**: exit-status glyphs / redraw races belong
  to the terminal surface, not wsdash output.
- Registry/score mutation without `store.locked()` will race concurrent launchd +
  git-hook jobs; atomic writes make it safe-ish, but keep the lock.
- `plutil`/plist edits by hand drift the watch set — always regen via `wsdash install`.

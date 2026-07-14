# wsdash Troubleshooting (0.2.0-beta.1)

Start with `wsdash doctor` — it checks python, git, state writability, registry,
cache integrity, the launchd plist + load state, watch-set sync, zero-idle, and the
memory ceiling, and its exit code is 0 only when everything passes.

## Chat / LLM Partner

| Symptom | Cause | Fix |
|---|---|---|
| `chat error: no model configured — set WSDASH_LLM_MODEL in .env.local` | No model set anywhere | Add `WSDASH_LLM_MODEL=…` to `~/.wsdash/.env.local` (see CONFIGURATION.md) |
| `chat error: URLError: … Connection refused` | Endpoint down / wrong `WSDASH_LLM_BASE_URL` | `curl <base>/models` to verify; start your local proxy; check the port |
| `chat error: HTTP 401/403 …` | Bad or missing API key | Set `WSDASH_LLM_API_KEY`; remember real env vars override `.env.local` |
| `warning: invalid WSDASH_LLM_TEMPERATURE='…', using 0.2` | Typo'd numeric config | Cosmetic — chat continues on the default; fix the value to silence it |
| Model answers but never uses tools | Some models need explicit nudging; provider may strip tool schemas | Ask explicitly ("use read_file to …"); verify with `/tools`; test the wire with `wsdash mcp call read_file '{"path":"/etc/hosts"}'` |
| Turn ends with `(stopped: exceeded max tool rounds)` | Model looped ≥20 tool calls | Re-ask more narrowly; check the transcript in `~/.wsdash/chat/` for what it attempted |
| Every confirmation is denied when scripting chat | By design: `confirm` fails closed without a TTY | Use `--mode allow`/`auto`/`yolo` deliberately, or run interactively |

## MCP / Desktop Commander

| Symptom | Cause | Fix |
|---|---|---|
| Banner shows `MCP OFF (cannot spawn MCP server …)` | `npx` missing or command wrong | `command -v npx`; test by hand: `npx -y @wonderwhy-er/desktop-commander`; override `WSDASH_MCP_COMMAND` |
| First chat start is slow (~10 s) | npx resolving/caching Desktop Commander | Subsequent starts use the npx cache; pin a local install and point `WSDASH_MCP_COMMAND` at it to eliminate |
| `MCP … timed out after Ns` | Server hung or died mid-call | The client kills and reports; restart chat. Check the tool's own logs if persistent |
| `TOOL ERROR (…)` in an answer | The tool itself failed (missing path, permission) | The message contains the server's error; act on it — chat keeps working |

## Dashboard / events

| Symptom | Cause | Fix |
|---|---|---|
| `no workspaces found under roots: …` | Roots don't contain projects at `max_depth` | Add roots in `~/.wsdash/config.json`, rerun `wsdash scan` |
| Doctor: `FAIL watch-set-current … run: wsdash install` | Workspace set changed since the agent was installed | `wsdash install` (idempotent) — regenerates the plist and re-bootstraps |
| Doctor: `FAIL launchd-loaded` | Agent not bootstrapped (fresh machine, or bootout) | `wsdash install`; inspect `launchctl print gui/$(id -u)/com.douglastalley.wsdash` |
| Scores feel stale after plain file edits | WatchPaths is shallow; no git op happened | Expected: the 5-min TTL catches it on next view; any git operation triggers instantly |
| Workspace shows `DISCONNECTED` | Its volume is unplugged | By design — last score retained; reconnect the volume and it recovers on the next event/view |
| `*.corrupt-<ts>` files in `~/.wsdash/state` | A state file failed to parse (crash mid-write is auto-safe; this is rarer) | Self-healing — recomputed automatically. `wsdash doctor --repair` purges the quarantine |
| A repo's pre-existing git hook stopped firing | It was chained, not removed | It now lives at `<hook>.pre-wsdash` and is exec'd by our hook; `wsdash uninstall` restores it |

## Recap

| Symptom | Cause | Fix |
|---|---|---|
| A harness shows `[unavailable]` | Its log dir/db doesn't exist on this machine | Informational, not an error |
| floyd harness listed with 0 sessions | DB present but quiet in the window | Expected — presence ≠ activity |
| Sessions missing from a very long transcript | Files >8 MB are read head+tail; single records >512 KB are skipped | Bounded by design (memory ceiling); narrow `--hours` windows lose less |
| `recap --hours -5` shows `last 1h` | Hours clamp to [1, 336] | Use a value in range |

## General

- **Where are errors logged?** launchd job output: `~/.wsdash/log/launchd.log`;
  event telemetry: `~/.wsdash/log/events.jsonl`; chat: `~/.wsdash/chat/*.jsonl`.
- **Memory check**: any command with `--mem` prints `peak_rss_mb=…` to stderr;
  `wsdash doctor` fails its `memory-ceiling` check above 50 MB.
- **Full reset**: `wsdash uninstall && rm -rf ~/.wsdash` — then `scan` + `install`
  to rebuild from scratch. Nothing outside `~/.wsdash`, the plist, and the git hooks
  is ever written by wsdash itself.

## FAQ

**Does wsdash run anything in the background?** No. launchd (the OS) watches paths
and spawns a short-lived hook process on change; between events there are zero
wsdash processes (`doctor`'s zero-idle check proves it).

**Does `failing_tests` run my tests?** Never. It reads pytest's `lastfailed` cache
and the optional `.wsdash-tests.json` contract file your own tooling can write.

**Can the Partner damage my system?** Tool calls are gated (see USER_MANUAL §6);
default mode confirms everything, non-TTY confirms fail closed, and `plan` mode
executes nothing. `yolo` removes all guards — that's what it's for. The `wsdash mcp
call` debug driver is ungated by design.

**Is my API key safe?** It's read from `.env.local` (0600), sent only in the auth
header to your configured endpoint, masked in diagnostics, and asserted absent from
error paths by the test suite.

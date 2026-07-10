# wsdash Security Notes (0.2.0-beta.1)

## Trust model

wsdash is a **local, single-user tool**. It reads your filesystem and harness logs,
and — through the LLM Partner — sends conversation content and tool results to the
LLM endpoint **you configure**. There is no telemetry, no phoning home, and no
network I/O besides (a) your configured LLM endpoint and (b) whatever the MCP server
you configure does (`npx` fetching Desktop Commander uses the npm registry).

## What leaves the machine

- Chat messages, the system prompt, tool schemas, and **tool results** (which can
  include file contents the model read) go to `WSDASH_LLM_BASE_URL`. Point that at
  a local proxy/model if data must stay on the machine — keyless local endpoints
  are a first-class path.
- `wsdash recap` itself is fully local. `recap --ask` routes through the Partner
  (so the recap text reaches the endpoint).

## Execution gating

- Every tool call is classified `read` / `write` / `dangerous`; unknown tools
  default to `write`. Modes: `plan` (nothing executes), `ask` (confirm all, the
  default), `allow` (reads auto), `auto` (dangerous confirms), `yolo` (no guards).
- Confirmations require a real TTY; **non-interactive `confirm` is a deny**
  (fail-closed). Denied/plan-blocked calls return notices that instruct the model
  not to retry.
- The confirmation gate requires an interactive human response; non-interactive
  callers cannot approve a write or dangerous action.
- `wsdash mcp call` is a deliberately ungated debug driver — same trust as running
  the MCP server yourself in a shell. Don't wire it into automation.

## Secrets and files

- `~/.wsdash/.env.local` holds the API key: keep `chmod 600` (the shipped file is).
  The key is never logged; diagnostics mask it; the test suite asserts it does not
  appear in error strings.
- Chat transcripts (`~/.wsdash/chat/*.jsonl`, **0600**) persist conversations AND
  tool outputs — treat them as sensitive; delete freely, nothing depends on them.
- Score/registry state files are 0600 (atomic tmp+rename writes).

## Injection surfaces (beta caveats)

- **Prompt injection**: recap scans third-party transcript logs and file contents;
  a hostile string in a scanned log or file becomes model context. The gates are the
  backstop — in `ask`/`allow`, an injected "write/delete X" still needs your y/N.
  Prefer `ask`/`allow` when recapping untrusted trees; avoid `yolo` there entirely.
- **`./.env.local` in a project directory** overrides your global LLM config when
  you run wsdash from that directory (standard dotenv semantics). Don't run
  `wsdash chat` from untrusted checkouts without checking for a planted `.env.local`
  (it could redirect your conversation to an attacker's endpoint).
- **Plugins** (`~/.wsdash/providers|views/*.py`) execute as you at load time — same
  trust as anything on your PATH. Only install plugins you've read.
- **Git hooks** installed by `wsdash install` run `wsdash hook git` in the
  background; they are chain-safe and restored on `wsdash uninstall`.

## Hardening verified in the 0.2.0-beta.1 QA pass

- Memory ceiling: 48.8 MB peak on a pathological corpus (giant diffs, 21.8 MB
  transcripts) via streamed subprocess I/O and bounded log readers; doctor gates 50 MB.
- Fault tolerance: atomic writes, corruption quarantine + self-heal, bounded flock,
  disconnected-volume degradation (observed live), dead-MCP-server detection,
  tolerant config parsing.
- Release QA found and fixed 9 issues, including world-readable transcripts and a
  memory ceiling breach.

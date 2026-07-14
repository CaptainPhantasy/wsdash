# wsdash Quick Start (0.2.0-beta.1)

Zero-idle workspace dashboard + LLM Partner for your terminal. 5 minutes, no dependencies
beyond macOS, Python 3.11+, and git (Node/npx only if you want Desktop Commander tools).

## 1. Install

wsdash is a plain directory — no pip, no build step.

```sh
# from the repository checkout, put both launchers on the PATH:
ln -sf "$PWD/bin/wsdash" ~/.local/bin/wsdash
ln -sf "$PWD/bin/mydash" ~/.local/bin/mydash

wsdash --version        # → wsdash 0.2.0b1
mydash --version         # → mydash 0.2.0b1
```

## 2. See your workspaces

```sh
wsdash scan     # discover repos/worktrees/session dirs under ~/sessions (+ editor workspaces)
wsdash          # dashboard: dirtiness 0-100, INCOMPLETE workspaces surfaced first
wsdash view --view detail <path>    # per-signal breakdown for one workspace
```

## 3. Turn on event-driven updates (recommended)

```sh
wsdash install  # launchd WatchPaths agent + git hooks (post-commit/checkout/merge/index-change)
wsdash doctor   # 10 health checks — all OK means you're wired up
```

No daemon runs. launchd spawns a short-lived `wsdash hook fs` only when a watched
path changes; otherwise the idle footprint is zero processes.

## 4. Configure the LLM Partner

```sh
cp .env.local.example ~/.wsdash/.env.local   # then edit
chmod 600 ~/.wsdash/.env.local
```

Minimal OpenAI-compatible config (works keyless against local proxies):

```sh
WSDASH_LLM_PROVIDER=openai
WSDASH_LLM_BASE_URL=http://127.0.0.1:17385/v1
WSDASH_LLM_MODEL=glm-5.2
```

Anthropic instead: `WSDASH_LLM_PROVIDER=anthropic`, `WSDASH_LLM_BASE_URL=https://api.anthropic.com`,
`WSDASH_LLM_API_KEY=sk-ant-…`, `WSDASH_LLM_MODEL=claude-sonnet-5`.

## 5. Chat, with gated tools

```sh
wsdash chat                  # REPL; default mode "ask" — every tool call needs your y/N
wsdash chat --mode allow     # read-only tools auto-run; writes still confirm
wsdash chat -m "question"    # one-shot
```

Inside the REPL: `/mode <plan|ask|allow|auto|yolo>`, `/tools`, `/recap`, `/clear`, `/quit`.

## 6. "Where did I leave off?"

```sh
wsdash recap                 # raw scan: Claude Code, Codex, floyd/ff/superfloyd, OMP + git diffs
wsdash chat -m "Where did I leave off yesterday? What should I pick up first?"
```

## Uninstall

```sh
wsdash uninstall             # removes launchd agent + restores chained git hooks
mydash uninstall             # same executable name, same behavior
rm ~/.local/bin/wsdash
rm ~/.local/bin/mydash
rm -rf ~/.wsdash             # state, config, transcripts
```

Next: [USER_MANUAL.md](USER_MANUAL.md) · [CONFIGURATION.md](CONFIGURATION.md) ·
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) · [SECURITY.md](SECURITY.md)

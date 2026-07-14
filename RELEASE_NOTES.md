# wsdash 0.2.0-beta.1 — Release Notes (2026-07-09)

**What it is:** a zero-idle, event-driven workspace dashboard for macOS that scores
how "incomplete" each of your projects is, plus an LLM Partner in your terminal that
can act on your machine through gated tools and answer *"where did I leave off?"*
from your actual AI-harness logs and git state.

**Status: beta.** Daily-drivable — it has run its own QA — but expect edges. Read
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) before relying on it hard.

## Highlights

- **Dashboard**: six measurable dirtiness signals → 0–100 score, 5-minute cache,
  INCOMPLETE workspaces surfaced first. `wsdash` renders and exits; nothing resides.
- **Event-driven, never polls**: launchd WatchPaths + git hooks trigger targeted
  recomputes; zero processes between events; <50 MB peak RSS enforced by `doctor`.
- **LLM Partner**: OpenAI-compatible or Anthropic endpoint from `.env.local`
  (keyless local proxies supported), Desktop Commander tools over MCP, five gate
  stages from `plan` (execute nothing) to `yolo` (no guards), 0600 transcripts.
- **Recap**: scans Claude Code, Codex (CLI + Desktop), floyd/ff/superfloyd, and
  OMP/OhMyPi/OpenMythos logs; shows per-project commits + diffs + open items; ask it
  in plain language and get ranked pick-this-up-first priorities.
- **Pluggable**: drop-in signal providers and views in `~/.wsdash/`, no core edits.

## Requirements

macOS (launchd, fsevents), Python 3.11+ (stdlib only), git. Node/npx only for
Desktop Commander. An OpenAI-compatible or Anthropic endpoint for the Partner
(dashboard and recap work fully without one).

## Install / upgrade

```sh
ln -sf <checkout>/bin/wsdash ~/.local/bin/wsdash
wsdash scan && wsdash install && wsdash doctor   # doctor: 10/10 OK expected
cp <checkout>/.env.local.example ~/.wsdash/.env.local && chmod 600 ~/.wsdash/.env.local
```

Docs: [QUICKSTART](docs/QUICKSTART.md) · [USER_MANUAL](docs/USER_MANUAL.md) ·
[CONFIGURATION](docs/CONFIGURATION.md) · [TROUBLESHOOTING](docs/TROUBLESHOOTING.md) ·
[SECURITY](docs/SECURITY.md)

## QA summary for this build

36/36 automated tests. Live checks covered launchd event → targeted recompute,
git-hook recompute, MCP integration, all five gate stages, and a 48.8 MB peak on a
worst-case corpus. Ten QA issues were found and fixed during the release pass.

## Beta caveats (short list)

- Anthropic wire is unit-tested, not yet live-tested here (openai wire is).
- Recap bounds very large transcripts (head+tail) — long sessions lose mid-detail.
- Model tool-use reliability depends on your endpoint; the loop caps at 20 rounds.
- `wsdash mcp call` bypasses gates by design (debug only).

Feedback: file an issue with a minimal, reproducible report.

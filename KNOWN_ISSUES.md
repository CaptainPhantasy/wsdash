# Known Issues — wsdash 0.2.0-beta.1

Open items at release. Everything here was observed during the QA pass on
2026-07-09; fixed issues are summarized in the changelog and release notes.

1. **Memory headroom is thin on pathological corpora.** Worst-case
   `recap --hours 24` peaked at 48.8 MB against a repo with a 3.5M-line dirty state
   and a 21.8 MB rollout — under the 50 MB ceiling but close. Next known sink if it
   ever breaches: JSON records up to the 512 KB line cap × parse overhead in the
   codex scanner. `wsdash doctor` will tell you.
2. **Recap detail is bounded by design.** Transcripts >8 MB are read first-200-lines
   + 2 MB tail; single JSONL records >512 KB are skipped. Very long sessions can
   lose mid-session detail in recaps (titles/first/last asks are still correct).
3. **Tool-calling reliability varies by model/broker.** glm-5.2 via the local
   omp-broker occasionally answers without using tools until asked explicitly. The
   loop is capped at 20 rounds; worst case you re-ask.
4. **Plain (non-git) file edits don't trigger instant recompute** unless they happen
   at the workspace top level. WatchPaths is shallow; the `.git` watch, git hooks,
   and the 5-minute TTL cover the gap. Known, accepted design trade-off.
5. **`wsdash mcp call` is ungated** (debug driver). Deliberate; documented in
   SECURITY.md. Don't script it.
6. **floyd.backup and similar copies appear as harnesses** in recap (any `~/.floyd*`
   dir with a `floyd.db` is listed). Cosmetic; a config exclude list is a candidate
   for 0.2.1.
7. **Non-repo session dirs contribute few signals** (`last_touch`, `failing_tests`
   only), so plain directories rarely reach INCOMPLETE. Signal ideas welcome via a
   provider plugin.
8. **External terminal automation:** when driving a web terminal with automation, a
   keystroke can race the prompt redraw and land a stray character in the buffer.
   This is not a wsdash bug; humans typing are unaffected.
9. **Anthropic wire is unit-tested but not yet live-tested** in this environment
   (no Anthropic endpoint configured on this machine during QA). The openai wire is
   live-verified end-to-end. First run against a real Anthropic key should be
   treated as beta-fresh.

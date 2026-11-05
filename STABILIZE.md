# wsdash stabilize (TOP10 #2)

Staff-internal packaging pass. Ops gate green ≠ ship.

**Accept kit:** [ACCEPT_wsdash.md](https://drive.google.com/file/d/15BBIm9o5dVFnr3M8BCTUUyBTcXi9Sv6a/view) (id `15BBIm9o5dVFnr3M8BCTUUyBTcXi9Sv6a`)  
**Product lock:** [PRODUCT_CUT_CONFIRMATIONS.md](https://drive.google.com/file/d/1ojF3aEfJC2LAWdNDPPb9MpIl0Oxk_OLl/view) · [PRODUCT_CUT_NOTES-v1.1.md](https://drive.google.com/file/d/1x3ZX_oxwnCprkgxu220M9SDauEOUtnT4/view)

## This PR (VM)

| Gate | Status |
|---|---|
| `python -m pytest -q` 37/37, exit 0 | required on this PR |
| `asyncio_default_fixture_loop_scope` set | **this PR** (`pyproject.toml`) |
| Open-work TODO/FIXME | **0** (Grace’s 8 reconciled; see below) |
| e2e against Douglas’s locked workspace | **Sofia on Mac-mini** — not this VM |

**Non-goals (Ethan cut):** no new LLM providers, no multi-user SaaS, no UI redesign, no Benchlink DNS, no Tailscale.

**Bug owner after package:** Sofia. Escalate via Floyd if blocked.

## pytest-asyncio loop-scope

HEAD `efb895c` had no asyncio setting in `pyproject.toml`. With `pytest-asyncio` installed, `python -m pytest -q -p no:cacheprovider` emitted:

`PytestDeprecationWarning _DEFAULT_FIXTURE_LOOP_SCOPE_UNSET`

This PR sets:

```toml
[tool.pytest.ini_options]
asyncio_default_fixture_loop_scope = "function"
asyncio_default_test_loop_scope = "function"
```

The suite is stdlib `unittest` (37 cases). The setting is required so pytest-asyncio does not warn when the same tests are collected via pytest. No async fixtures were added.

## TODO reconciliation (Grace’s 8, not Larry’s 11)

Ethan: Larry’s “11” was an inventory marker-string scan, not open-work triage. **Canonical count is Grace’s 8.** Product gate = **0 open-work TODO/FIXME** once those 8 are classified.

Command (ACCEPT E2, plus exclude this packaging note so quoting the inventory does not inflate the count):

```sh
grep -rnwE "TODO|FIXME" -I . --exclude-dir=.venv --exclude-dir=.git --exclude=STABILIZE.md
```

Grace’s 8 were counted on HEAD before `STABILIZE.md` existed. Re-running the original command after this file landed also matches this note. `--exclude=STABILIZE.md` keeps the canonical eight reproducible.

| File | Hits | Kind | Disposition |
|---|---:|---|---|
| `CHANGELOG.md` | 1 | docs: “new TODO markers” as a scored signal | keep — product copy |
| `docs/USER_MANUAL.md` | 1 | docs: `todo_markers` signal | keep — product copy |
| `tests/test_wsdash.py` | 4 | fixture + comments planting `# TODO` / `# FIXME` for the detector | keep — detector fixtures; do not strip |
| `wsdash/providers/todo_markers.py` | 2 | detector docstring + `MARK_B` regex | keep — the feature |

**Open-work TODOs: 0.** None of the 8 is unfinished implementation. Do not “clear” detector strings or test fixtures.

`wsdash/llm/toolkit.py` contains “new TODOs” (plural). Word-boundary `TODO|FIXME` does not match it; it is the same detector description, not a ninth work item.

KNOWN_ISSUES.md items stay known non-blockers this cycle unless Sofia flags one as ship-stopping.

## e2e accept evidence (not this VM)

Douglas locked the real workspace:

`/Volumes/Storage/Floyds_Labs_Staff` on the **Mac mini**.

This Cursor VM cannot mount that path. A scratch/temp tree on the VM is **not** accept evidence and must not be reported as that path.

**Owner:** Sofia  
**Where:** Mac-mini.local  
**How:** Desktop Commander, checkout of this PR branch (or `main` after merge)  
**What to record:** `wsdash --version`, `wsdash scan`, `wsdash` (or `wsdash view`) against `/Volumes/Storage/Floyds_Labs_Staff`, command + output, no paid LLM required for the dashboard path.

## Remaining gaps vs ship (deferred)

- **e2e log** — Sofia, as above.
- **Claire light** — local/dev LLM key only if recap/chat is used; no brand Stripe. Not probed on this VM.
- **`[dev]` extra** — `pip` reports none. Informational; not in Ethan’s cut.
- **KNOWN_ISSUES.md** — memory headroom, recap bounds, model tool-use reliability, shallow WatchPaths, ungated `mcp call`, floyd.backup listed as a harness, Anthropic wire unit-tested only. Non-blockers this cycle.
- **macOS-only installer** — launchd / `wsdash install` is not claimed green on Linux CI/VMs.
- **`wsdash.cli:main` size** — ~800 LOC lazy dispatch left as-is (no split this pass).

## Verify on this PR

```sh
python -m pytest -q -p no:cacheprovider
# expect: 37 passed, exit 0, no asyncio_default_fixture_loop_scope warning
```

# wsdash

![wsdash — Floyd's Labs](assets/hero.jpg)

## Or: another brick in the unfinished pile

You left the work somewhere. wsdash scores it — Git changes, stale worktrees, failing tests, the rest of the mess — prints a table, and exits. Nothing sits in the background charging rent.

Built at Floyd's Labs, in a garage in Brown County, Indiana. The coffee tastes like motor oil. 2:47 AM is a normal shift. Tools have to earn the desk.

**Pick up the work you left behind.**

[Download v0.2.1](https://github.com/CaptainPhantasy/wsdash/releases/tag/v0.2.1) · [Report a bug](https://github.com/CaptainPhantasy/wsdash/issues) · [Floyd's Labs](https://floydslabs.com)

## Get it running

Requirements: **Python 3.11+ and Git.** macOS adds optional launchd watchers; Linux uses Git hooks plus cron or a systemd timer.

Two doors. Same commands on the other side: `wsdash` and `mydash`. `wsdash --version` prints `wsdash 0.2.1`.

### Release wheel

Download `wsdash-0.2.1-py3-none-any.whl` from the [v0.2.1 release](https://github.com/CaptainPhantasy/wsdash/releases/tag/v0.2.1), then install it in its own virtualenv:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./wsdash-0.2.1-py3-none-any.whl
.venv/bin/wsdash --version
.venv/bin/wsdash scan
.venv/bin/wsdash
```

Call the binaries by path, or activate the virtualenv so `wsdash` is on your PATH.

### Checkout

From a clone, symlink the launchers in `bin/`. No pip. Run this from the repository root:

```sh
ln -sf "$PWD/bin/wsdash" ~/.local/bin/wsdash
ln -sf "$PWD/bin/mydash" ~/.local/bin/mydash
wsdash --version
wsdash scan
wsdash
```

`~/.local/bin` has to be on your PATH.

The core dashboard needs no third-party Python packages. `wsdash install` is the step that puts managed Git hooks (and, on macOS, launchd watchers) on the machine. On Linux it installs the hooks, skips launchd, and prints a cron line you can use for periodic refresh. The ordinary dashboard does not do that. You run it, it prints, it leaves. `wsdash uninstall` takes those watchers and hooks back off. Without a terminal, pass `--yes`.

A score is unfinished work, not a grade. High means you left a mess. It does not mean the project is bad. Deep edits can miss the launchd watch, because WatchPaths is shallow. Git hooks, or the cache expiring, still catch them.

Chat is optional. It wants your own provider credentials, and it can send selected context to that provider. Read [Security](docs/SECURITY.md), [Configuration](docs/CONFIGURATION.md), and [Known Issues](KNOWN_ISSUES.md) before you turn it on.

## What the terminal says

Screenshots from a local fixture under `~/projects`. `bench` is unfinished and sorts first. `quiet-notes` is fine. `unplugged` is a path that left. No keys. Not a mockup.

![table view: INCOMPLETE first, then ok, then disconnected](docs/screenshots/table.png)

Status leads the row. Higher score means more unfinished work, and that row is listed first. `INCOMPLETE` is the loud label. `disconnected` means the path is missing and the last score is kept.

![detail view: signals ordered by how much they add](docs/screenshots/detail.png)

![doctor on Linux: launchd is skipped, every other check passes](docs/screenshots/doctor.png)

`wsdash doctor` prints a `next:` line when a check fails. This capture is from Linux, so the launchd check reads `SKIP`. On a Mac it checks the agent, and `wsdash install` is the fix it points at.

## What is in the box

The release includes `wsdash-0.2.1-py3-none-any.whl`, source where applicable, and `SHA256SUMS.txt`. Install from the tagged release's named assets. GitHub's automatic source archives are snapshots, not the release. After you download the matching files, check them:

```sh
shasum -a 256 -c SHA256SUMS.txt
```

## Show the work

```sh
python3 -m unittest discover -s tests -v
```

That covers workspace scoring, state storage, the CLI, and stubbed LLM/MCP behavior. The wheel is installed and run again in a fresh virtualenv. Paid provider calls are not in the suite.

## When it breaks

Open an issue with your platform, the version, the command, and the smallest reproduction you can stand. Leave credentials and personal transcripts out. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

wsdash is free software under the GNU Affero General Public License, version 3 or any later version (`AGPL-3.0-or-later`). See [LICENSE](LICENSE). If you run a modified version for other people over a network, you must offer them its source code.

---

Bella checks the keyboard. Bowser watches the router.

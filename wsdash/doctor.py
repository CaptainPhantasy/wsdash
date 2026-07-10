"""Health, fault-tolerance and guarantee checks: state integrity, launchd status,
watch-set drift, zero-idle verification, memory ceiling report, repair."""
import glob
import os
import resource
import shutil
import subprocess
import sys

from . import config, discover, installer, store

MEMORY_CEILING_MB = config.LIMITS.get("memory_ceiling_mb", 50.0)


def peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024  # macOS: bytes


def idle_processes() -> list:
    """Background wsdash processes other than this one — must be empty between
    invocations. Processes with a controlling TTY are the user's own interactive
    sessions (e.g. a chat REPL), not strays."""
    try:
        cp = subprocess.run(["pgrep", "-f", "bin/wsdash"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    me, parent = os.getpid(), os.getppid()
    stray = []
    for p in cp.stdout.split():
        if not p.strip() or int(p) in (me, parent):
            continue
        try:
            tty = subprocess.run(["ps", "-o", "tty=", "-p", p], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            tty = ""
        if tty in ("", "??", "?"):  # no TTY => background => stray
            stray.append(p)
    return stray


def run_checks(cfg: dict) -> list:
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("python", sys.version_info >= (3, 9), sys.version.split()[0])
    add("git", shutil.which("git") is not None, shutil.which("git") or "not found")
    try:
        store.ensure_dirs()
        probe = os.path.join(store.state_dir(), ".probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.unlink(probe)
        add("state-writable", True, store.state_dir())
    except OSError as exc:
        add("state-writable", False, str(exc))

    reg = store.load_registry()
    n = len(reg["workspaces"])
    missing = [w["name"] for w in reg["workspaces"].values() if w.get("missing")]
    add("registry", True, f"{n} workspaces, {len(missing)} disconnected"
        + (f" ({', '.join(missing[:5])})" if missing else ""))
    corrupt = glob.glob(os.path.join(store.state_dir(), "*.corrupt-*"))
    add("cache-integrity", not corrupt, f"{len(corrupt)} quarantined corrupt files")

    plist = installer.plist_path(cfg)
    add("launchd-plist", os.path.exists(plist), plist)
    add("launchd-loaded", installer.agent_loaded(cfg),
        f"gui/{os.getuid()}/{cfg['launchd_label']}")
    drift = os.path.exists(os.path.join(config.home(), "watch-drift"))
    add("watch-set-current", not drift,
        "workspace set changed since install — run: wsdash install" if drift else "in sync")

    stray = idle_processes()
    add("zero-idle", not stray, f"{len(stray)} stray wsdash processes" + (f": {stray}" if stray else ""))
    mem = peak_rss_mb()
    add("memory-ceiling", mem < MEMORY_CEILING_MB, f"peak RSS {mem:.1f} MB (ceiling {MEMORY_CEILING_MB:.0f} MB)")
    return checks


def repair(cfg: dict) -> dict:
    """Recover from interruption/corruption: quarantine handled by store on read;
    rebuild the registry from a fresh scan; purge quarantined files."""
    purged = 0
    for p in glob.glob(os.path.join(store.state_dir(), "*.corrupt-*")):
        os.unlink(p)
        purged += 1
    with store.locked():
        reg = discover.sync_registry(cfg)
    return {"purged_corrupt": purged, "workspaces": len(reg["workspaces"])}

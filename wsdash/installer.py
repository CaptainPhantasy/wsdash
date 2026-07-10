"""Orchestration installer: launchd WatchPaths agent (fsevents-backed, spawns a
short-lived `wsdash hook fs` job on change — no resident daemon of ours) and
chain-safe git hooks (post-commit/checkout/merge/index-change).
"""
import os
import plistlib
import stat
import subprocess
import sys

from . import config, gitutil, store

GIT_HOOKS = ["post-commit", "post-checkout", "post-merge", "post-index-change"]
HOOK_MARK = "# wsdash-managed-hook v1"


def wsdash_bin() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "bin", "wsdash")


def plist_path(cfg: dict) -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{cfg['launchd_label']}.plist")


def watch_paths(cfg: dict, reg: dict) -> list:
    paths = set(config.roots(cfg))
    for ws in reg["workspaces"].values():
        if ws.get("missing") or not os.path.isdir(ws["path"]):
            continue
        paths.add(ws["path"])
        if ws["kind"] in ("repo", "worktree"):
            cd = gitutil.common_dir(ws["path"])
            if cd and os.path.isdir(cd):
                paths.add(cd)
    return sorted(paths)


def build_plist(cfg: dict, reg: dict) -> dict:
    return {
        "Label": cfg["launchd_label"],
        "ProgramArguments": [sys.executable, wsdash_bin(), "hook", "fs"],
        "WatchPaths": watch_paths(cfg, reg),
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": os.path.join(store.log_dir(), "launchd.log"),
        "StandardErrorPath": os.path.join(store.log_dir(), "launchd.log"),
        "EnvironmentVariables": {"WSDASH_HOME": config.home()},
    }


def read_plist_watch_paths(path: str) -> list:
    try:
        with open(path, "rb") as f:
            return plistlib.load(f).get("WatchPaths", [])
    except (OSError, plistlib.InvalidFileException):
        return []


def _launchctl(*args) -> tuple:
    try:
        cp = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)
        return cp.returncode, (cp.stdout + cp.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)


def agent_loaded(cfg: dict) -> bool:
    rc, _ = _launchctl("print", f"gui/{os.getuid()}/{cfg['launchd_label']}")
    return rc == 0


def install_launchd(cfg: dict, reg: dict) -> dict:
    store.ensure_dirs()
    path = plist_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(build_plist(cfg, reg), f)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{cfg['launchd_label']}")  # idempotent reinstall
    rc, out = _launchctl("bootstrap", domain, path)
    marker = os.path.join(config.home(), "watch-drift")
    if os.path.exists(marker):
        os.unlink(marker)
    return {"plist": path, "bootstrap_rc": rc, "bootstrap_out": out,
            "loaded": agent_loaded(cfg), "watch_paths": len(read_plist_watch_paths(path))}


def uninstall_launchd(cfg: dict) -> dict:
    rc, out = _launchctl("bootout", f"gui/{os.getuid()}/{cfg['launchd_label']}")
    path = plist_path(cfg)
    existed = os.path.exists(path)
    if existed:
        os.unlink(path)
    return {"bootout_rc": rc, "removed_plist": existed}


# ---- git hooks -------------------------------------------------------------------

def _hook_body(cfg: dict, hooks_dir: str, name: str) -> str:
    chained = os.path.join(hooks_dir, f"{name}.pre-wsdash")
    return f"""#!/bin/sh
{HOOK_MARK}
export WSDASH_HOME="{config.home()}"
"{sys.executable}" "{wsdash_bin()}" hook git "$PWD" >/dev/null 2>&1 &
[ -x "{chained}" ] && exec "{chained}" "$@"
exit 0
"""


def install_git_hooks(cfg: dict, reg: dict) -> list:
    results = []
    seen = set()
    for ws in reg["workspaces"].values():
        if ws["kind"] != "repo" or ws.get("missing"):
            continue
        cd = gitutil.common_dir(ws["path"])
        if not cd or cd in seen:
            continue
        seen.add(cd)
        hooks_dir = os.path.join(cd, "hooks")
        os.makedirs(hooks_dir, exist_ok=True)
        for name in GIT_HOOKS:
            hp = os.path.join(hooks_dir, name)
            if os.path.exists(hp):
                with open(hp, "r", encoding="utf-8", errors="replace") as f:
                    body = f.read()
                if HOOK_MARK in body:
                    pass  # ours — overwrite below (idempotent refresh)
                else:
                    os.replace(hp, os.path.join(hooks_dir, f"{name}.pre-wsdash"))
            with open(hp, "w", encoding="utf-8") as f:
                f.write(_hook_body(cfg, hooks_dir, name))
            os.chmod(hp, os.stat(hp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            results.append(hp)
    return results


def uninstall_git_hooks(cfg: dict, reg: dict) -> list:
    removed = []
    for ws in reg["workspaces"].values():
        if ws["kind"] != "repo" or ws.get("missing"):
            continue
        cd = gitutil.common_dir(ws["path"])
        if not cd:
            continue
        hooks_dir = os.path.join(cd, "hooks")
        for name in GIT_HOOKS:
            hp = os.path.join(hooks_dir, name)
            try:
                with open(hp, "r", encoding="utf-8", errors="replace") as f:
                    ours = HOOK_MARK in f.read()
            except OSError:
                continue
            if not ours:
                continue
            os.unlink(hp)
            chained = os.path.join(hooks_dir, f"{name}.pre-wsdash")
            if os.path.exists(chained):
                os.replace(chained, hp)
            removed.append(hp)
    return removed

"""Thin, timeout-bounded git subprocess helpers (no external deps)."""
import os
import subprocess


def run(args, cwd, timeout: int = 15, binary: bool = False):
    """Returns (rc, output). rc=-1 on OS/timeout failure — callers treat as 'unavailable'."""
    try:
        cp = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return -1, b"" if binary else ""
    out = cp.stdout if binary else cp.stdout.decode("utf-8", errors="replace")
    return cp.returncode, out


def run_stream(args, cwd, timeout: int = 30, line_cb=None):
    """Stream git output without accumulating it: returns (rc, total_bytes).
    Keeps memory flat on arbitrarily large diffs; optional line_cb sees each
    decoded line (used for marker counting)."""
    try:
        proc = subprocess.Popen(
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
        )
    except OSError:
        return -1, 0
    total = 0
    buf = b""
    try:
        import time as _t
        deadline = _t.monotonic() + timeout
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if line_cb:
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line_cb(line)
            else:
                buf = b""
            if _t.monotonic() > deadline:
                proc.kill()
                return -1, total
        if line_cb and buf:
            line_cb(buf)
        rc = proc.wait(timeout=5)
        return rc, total
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        return -1, total
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=1)


def is_repo(path: str) -> bool:
    g = os.path.join(path, ".git")
    return os.path.isdir(g) or os.path.isfile(g)


def common_dir(path: str) -> str | None:
    rc, out = run(["rev-parse", "--git-common-dir"], path)
    if rc != 0 or not out.strip():
        return None
    p = out.strip()
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(path, p))


def default_branch(path: str) -> str:
    rc, out = run(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], path)
    if rc == 0 and out.strip():
        return out.strip().split("/", 1)[-1]
    for cand in ("main", "master"):
        rc, _ = run(["show-ref", "--verify", "--quiet", f"refs/heads/{cand}"], path)
        if rc == 0:
            return cand
    return "HEAD"

"""Spawn, health-check, and stop hai-agent-runtime processes (sync, loopback-only)."""

from __future__ import annotations

import logging
import os
import pathlib
import signal
import subprocess
import time
import typing

import httpx

from .errors import RuntimeStartTimeoutError, RuntimeUnhealthyError

logger = logging.getLogger(__name__)

LOOPBACK_HOST = "127.0.0.1"
SPAWN_TIMEOUT_S = 45.0
HEALTH_POLL_INTERVAL_S = 0.25
TERM_GRACE_S = 2.0
LOG_TAIL_CHARS = 4000


def probe_health(base_url: str) -> typing.Optional[typing.Dict[str, typing.Any]]:
    """The /health JSON body on a 200 ({} for non-JSON bodies); None when unreachable/unhealthy."""
    try:
        response = httpx.get(f"{base_url}/health", timeout=2.0)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def spawn(cmd: typing.List[str], *, env: typing.Dict[str, str], log_path: pathlib.Path) -> subprocess.Popen:
    """Start the runtime in its own process group with stderr to `log_path`.

    stderr goes to a file, not a pipe: nobody drains a pipe after spawn, so the
    buffer would fill and block. Own process group so we can reap grandchildren
    (e.g. desktop helpers) the binary may spawn.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("spawning hai-agent-runtime: %s (stderr -> %s)", " ".join(cmd), log_path)
    with log_path.open("wb") as log_file:  # child inherits the fd; the parent handle can close right away
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=log_file,
            env=env,
            start_new_session=os.name == "posix",
            creationflags=0 if os.name == "posix" else getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )


def wait_healthy(
    base_url: str, proc: subprocess.Popen, *, timeout_s: float, log_path: pathlib.Path
) -> typing.Dict[str, typing.Any]:
    """Poll /health until 200; raises RuntimeUnhealthyError (child exited) or RuntimeStartTimeoutError."""
    deadline = time.monotonic() + timeout_s
    while True:
        payload = probe_health(base_url)
        if payload is not None:
            logger.info("hai-agent-runtime ready (pid %d)", proc.pid)
            return payload
        if proc.poll() is not None:
            raise RuntimeUnhealthyError(
                f"hai-agent-runtime exited with code {proc.returncode}: {log_tail(log_path)} (full log: {log_path})"
            )
        if time.monotonic() >= deadline:
            raise RuntimeStartTimeoutError(
                f"hai-agent-runtime did not become healthy within {timeout_s:.0f}s (see {log_path})"
            )
        time.sleep(HEALTH_POLL_INTERVAL_S)


def log_tail(path: pathlib.Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "(stderr log unreadable)"
    if not text:
        return "(no stderr output)"
    return text[-LOG_TAIL_CHARS:]


def _killpg_posix(pid: int, sig: int) -> bool:
    """Send `sig` to `pid`'s process group; False if the process/group is already gone."""
    try:
        os.killpg(os.getpgid(pid), sig)
    except (OSError, ProcessLookupError):
        return False
    return True


def kill_process_group(pid: int) -> bool:
    """Force-kill the runtime's process group by pid; False if it was already gone."""
    if os.name == "posix":
        return _killpg_posix(pid, signal.SIGKILL)
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _signal(proc: subprocess.Popen, *, force: bool) -> bool:
    """Signal the runtime's whole process group (posix) or just the process; False if already gone."""
    if os.name == "posix":
        return _killpg_posix(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
    try:
        if force:
            proc.kill()
        else:
            proc.terminate()
    except (OSError, ProcessLookupError):
        return False
    return True


def terminate(proc: subprocess.Popen) -> None:
    """Graceful stop: SIGTERM the group, wait the grace period, then SIGKILL the group."""
    if proc.poll() is not None:
        return
    if not _signal(proc, force=False):
        return
    try:
        proc.wait(timeout=TERM_GRACE_S)
        return
    except subprocess.TimeoutExpired:
        pass
    if _signal(proc, force=True):
        try:
            proc.wait(timeout=TERM_GRACE_S)
        except subprocess.TimeoutExpired:
            logger.warning("hai-agent-runtime (pid %d) did not exit after forced kill", proc.pid)

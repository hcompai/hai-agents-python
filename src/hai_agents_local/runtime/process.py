"""Spawn, health-check, and stop hai-agent-runtime processes (sync, loopback-only)."""

from __future__ import annotations

import logging
import os
import pathlib
import signal
import subprocess
import threading
import time
import typing

import httpx

from . import identity
from .errors import RuntimeStartTimeoutError, RuntimeUnhealthyError

logger = logging.getLogger(__name__)

LOOPBACK_HOST = "127.0.0.1"
SPAWN_TIMEOUT_S = 45.0
HEALTH_POLL_INTERVAL_S = 0.25
# Exceeds the runtime's own shutdown teardown (10 s), which releases cloud environments.
TERM_GRACE_S = 15.0
KILL_WAIT_S = 2.0
LOG_TAIL_CHARS = 4000


def responds(base_url: str) -> bool:
    """Whether any HTTP server answers at `base_url`, proven or not."""
    try:
        httpx.get(f"{base_url}/health", timeout=2.0, trust_env=False)
    except httpx.HTTPError:
        return False
    return True


def probe_health(base_url: str, token: str) -> typing.Optional[typing.Dict[str, typing.Any]]:
    """The proven /health JSON body on a 200 ({} for non-JSON bodies); None when unreachable/unhealthy."""
    try:
        with identity.http_client(token, timeout=2.0) as client:
            response = client.get(f"{base_url}/health")
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
    """Start the runtime in its own process group (to reap grandchildren); stderr to a file, as nobody drains a pipe."""
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
    base_url: str,
    proc: subprocess.Popen,
    *,
    token: str,
    timeout_s: float,
    log_path: pathlib.Path,
    cancel_event: typing.Optional[threading.Event] = None,
) -> typing.Dict[str, typing.Any]:
    """Poll /health until a proven 200; raises LocalRuntimeError if another server answers, or the child fails."""
    deadline = time.monotonic() + timeout_s
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeUnhealthyError("runtime startup cancelled")
        payload = probe_health(base_url, token)
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
    """Signal the runtime's whole process tree; False if it was already gone."""
    if os.name == "posix":
        return _killpg_posix(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
    try:
        # No portable graceful group signal on Windows; /F keeps a .cmd-shim child from outliving it.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
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
            proc.wait(timeout=KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            logger.warning("hai-agent-runtime (pid %d) did not exit after forced kill", proc.pid)

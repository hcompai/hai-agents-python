"""Machine-wide desktop claim: at most one process drives this machine's mouse and keyboard at a time."""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time

from .file_lock import try_lock, unlock
from .killswitch import STOP_PATH

LOCK_PATH = STOP_PATH.parent / "desktop.lock"
# Covers a previous agent process that is still shutting down.
CLAIM_GRACE_S = 10.0
CLAIM_POLL_S = 0.1


class DesktopBusyError(RuntimeError):
    """Another process is driving this machine's desktop."""


_process_lock = threading.Lock()
_holders = 0
_fd: int | None = None


def _claim_for_process() -> bool:
    global _holders, _fd
    with _process_lock:
        if _holders == 0:
            LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
            if not try_lock(fd):
                os.close(fd)
                return False
            _fd = fd
        _holders += 1
        return True


def _release_for_process() -> None:
    global _holders, _fd
    with _process_lock:
        _holders -= 1
        if _holders == 0 and _fd is not None:
            unlock(_fd)
            os.close(_fd)
            _fd = None


class DesktopClaim:
    """One bridge's share of this process's desktop lock; bridges in one process share it, other processes wait."""

    def __init__(self) -> None:
        self._held = False

    async def acquire(self, stop: asyncio.Event) -> bool:
        """Wait up to CLAIM_GRACE_S for the desktop; False when ``stop`` fires first, DesktopBusyError on timeout."""
        deadline = time.monotonic() + CLAIM_GRACE_S
        while not _claim_for_process():
            if stop.is_set():
                return False
            if time.monotonic() >= deadline:
                raise DesktopBusyError(
                    "another agent is driving this desktop; wait for it to finish or stop it with `holo local stop`"
                )
            with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                await asyncio.wait_for(stop.wait(), CLAIM_POLL_S)
        self._held = True
        return True

    def release(self) -> None:
        if self._held:
            self._held = False
            _release_for_process()

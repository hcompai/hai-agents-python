"""Machine-wide desktop claim: at most one process drives this machine's mouse and keyboard at a time."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time

from .killswitch import STOP_PATH

LOCK_PATH = STOP_PATH.parent / "desktop.lock"
# Covers a previous agent process that is still shutting down.
CLAIM_GRACE_S = 10.0
CLAIM_POLL_S = 0.1

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)


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
            if not _try_lock(fd):
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
            _unlock(_fd)
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
                    "another agent is driving this desktop; wait for it to finish or stop it with `hai local stop`"
                )
            with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                await asyncio.wait_for(stop.wait(), CLAIM_POLL_S)
        self._held = True
        return True

    def release(self) -> None:
        if self._held:
            self._held = False
            _release_for_process()

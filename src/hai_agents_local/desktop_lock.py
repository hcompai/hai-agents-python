"""Machine-wide desktop claim: at most one bridge drives this machine's mouse and keyboard at a time."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time

from .killswitch import STOP_PATH

LOCK_PATH = STOP_PATH.parent / "desktop.lock"
# Covers an in-process bridge displaced by a newer session, which releases once its stop lands.
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
    """Another bridge, in this process or another, is driving this machine's desktop."""


class DesktopClaim:
    """One holder's claim on the desktop lock; each claim opens its own fd, so claims contend even in one process."""

    def __init__(self) -> None:
        self._fd: int | None = None

    async def acquire(self, stop: asyncio.Event) -> bool:
        """Wait up to CLAIM_GRACE_S for the desktop; False when ``stop`` fires first, DesktopBusyError on timeout."""
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + CLAIM_GRACE_S
        while not _try_lock(fd):
            if stop.is_set():
                os.close(fd)
                return False
            if time.monotonic() >= deadline:
                os.close(fd)
                raise DesktopBusyError(
                    "another agent is driving this desktop; wait for it to finish or stop it with `hai local stop`"
                )
            with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                await asyncio.wait_for(stop.wait(), CLAIM_POLL_S)
        self._fd = fd
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            _unlock(fd)
            os.close(fd)

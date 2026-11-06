"""A non-blocking exclusive lock on an open file, which the operating system drops with the process."""

from __future__ import annotations

import contextlib
import os
import sys

if sys.platform == "win32":
    import msvcrt

    def try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)

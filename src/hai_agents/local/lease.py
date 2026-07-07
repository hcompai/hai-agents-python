"""Per-environment-kind machine lease backed by an OS file lock, released by the OS if the holder dies."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import IO

from .errors import BridgeBusyError

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

LEASE_DIR = Path.home() / ".hai"


class MachineLease:
    """Holds ``bridge-{kind}.lock`` with the owner's session_id as its content."""

    def __init__(self, environment_kind: str, session_id: str) -> None:
        self._environment_kind = environment_kind
        self._session_id = session_id
        self._handle: IO[str] | None = None

    @property
    def _path(self) -> Path:
        return LEASE_DIR / f"bridge-{self._environment_kind}.lock"

    def acquire(self) -> None:
        """Take the kind lock; raises BridgeBusyError when the holder serves the same
        session (benign, another process covers it) and RuntimeError otherwise."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+")
        try:
            _lock(handle)
        except OSError as exc:
            handle.close()
            if self._read_holder() == self._session_id:
                raise BridgeBusyError(f"another bridge already serves session {self._session_id}") from exc
            raise RuntimeError(
                f"another process already serves a local {self._environment_kind} environment on this machine"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(self._session_id)
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is not None:
            try:
                self._handle.seek(0)
                self._handle.truncate()
                self._handle.flush()
                _unlock(self._handle)
            finally:
                self._handle.close()
                self._handle = None

    def _read_holder(self) -> str | None:
        try:
            return self._path.read_text().strip()
        except OSError:
            return None


if sys.platform == "win32":

    def _lock(handle: IO[str]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: IO[str]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:

    def _lock(handle: IO[str]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: IO[str]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

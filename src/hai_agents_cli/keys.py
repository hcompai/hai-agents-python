"""Watch the terminal for a lone Esc while a turn streams, without blocking the main thread."""

from __future__ import annotations

import contextlib
import os
import select
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any

ESC = b"\x1b"
_POLL_S = 0.1


def supported() -> bool:
    return sys.platform != "win32" and sys.stdin.isatty()


class EscWatcher:
    """Calls ``on_esc(watcher)`` on its own thread when Esc is pressed; a no-op off a TTY or on Windows."""

    def __init__(self, on_esc: Callable[[EscWatcher], None]) -> None:
        self._on_esc = on_esc
        self._stop = threading.Event()
        self._abandoned = threading.Event()
        self._thread: threading.Thread | None = None
        self._fd: int | None = None
        self._saved: Any = None
        self._tty_lock = threading.Lock()

    def __enter__(self) -> EscWatcher:
        if not supported():
            return self
        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        self._thread = threading.Thread(target=self._run, daemon=True, name="hai-esc-watcher")
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        # On a clean exit, wait out a prompt the user is still typing; on ctrl+c, abandon it and leave the daemon behind.
        self._stop.set()
        try:
            if self._thread is not None and exc_type is None:
                self._thread.join()
        finally:
            with self._tty_lock:
                self._abandoned.set()
                self._restore()

    @property
    def stopped(self) -> bool:
        """The turn ended under an open prompt, so whatever was typed belongs to no one."""
        return self._abandoned.is_set()

    @contextlib.contextmanager
    def cooked(self) -> Iterator[None]:
        """Normal line editing for a prompt typed mid-turn."""
        with self._tty_lock:
            if not self._abandoned.is_set():
                self._restore()
        try:
            yield
        finally:
            with self._tty_lock:
                if self._fd is not None and not self._abandoned.is_set():
                    import tty

                    tty.setcbreak(self._fd)

    def read_line(self) -> str | None:
        """A line typed in cooked mode; None on EOF or once abandoned, so it never eats the next prompt's input."""
        assert self._fd is not None
        typed = b""
        while not self._abandoned.is_set():
            ready, _, _ = select.select([self._fd], [], [], _POLL_S)
            if not ready:
                continue
            chunk = os.read(self._fd, 1024)
            if not chunk:
                return None
            typed += chunk
            if typed.endswith(b"\n"):
                return typed.decode(errors="replace").rstrip("\n")
        return None

    def _run(self) -> None:
        assert self._fd is not None
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], _POLL_S)
            if ready and os.read(self._fd, 32) == ESC:
                self._on_esc(self)

    def _restore(self) -> None:
        if self._fd is not None and self._saved is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

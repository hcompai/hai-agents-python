"""Read the keyboard while a turn streams, without blocking the main thread."""

from __future__ import annotations

import codecs
import os
import select
import sys
import threading
from collections.abc import Callable
from typing import Any

ESC = b"\x1b"
_POLL_S = 0.1


def supported() -> bool:
    return sys.platform != "win32" and sys.stdin.isatty()


def edit(text: str, typed: str) -> tuple[str, bool]:
    """Apply typed keys to a one-line input; True once enter is pressed. Escape sequences (arrows) are ignored."""
    for char in typed:
        if char in "\r\n":
            return text, True
        if char == "\x1b":
            break
        if char in "\x7f\b":
            text = text[:-1]
        elif char == "\x15":
            text = ""
        elif char == "\x17":
            text = text.rstrip()
            text = text[: len(text) - len(text.split(" ")[-1])]
        elif char.isprintable():
            text += char
    return text, False


class EscWatcher:
    """On its own thread, calls ``on_esc()`` on a lone Esc and ``on_keys(typed)`` for any other keys.

    A no-op off a TTY or on Windows.
    """

    def __init__(self, on_esc: Callable[[], None], on_keys: Callable[[str], None] | None = None) -> None:
        self._on_esc = on_esc
        self._on_keys = on_keys
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
        # On ctrl+c, leave the daemon behind rather than wait on a callback still talking to the API.
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
        """The turn ended; work started from a key press belongs to no one."""
        return self._abandoned.is_set()

    def _run(self) -> None:
        assert self._fd is not None
        decode = codecs.getincrementaldecoder("utf-8")(errors="ignore").decode
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], _POLL_S)
            if not ready:
                continue
            chunk = os.read(self._fd, 1024)
            if chunk == ESC:
                self._on_esc()
            elif self._on_keys is not None and (typed := decode(chunk)):
                self._on_keys(typed)

    def _restore(self) -> None:
        if self._fd is not None and self._saved is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

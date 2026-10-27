"""Watch the terminal for a lone Esc while a turn streams, without blocking the main thread."""

from __future__ import annotations

import codecs
import os
import select
import sys
import threading
from collections.abc import Callable
from typing import Any

from rich.cells import cell_len

ESC = b"\x1b"
_POLL_S = 0.1
_UP_CLEARING = "\x1b[1A\x1b[2K"


def supported() -> bool:
    return sys.platform != "win32" and sys.stdin.isatty()


class EscWatcher:
    """On its own thread, calls ``on_esc(watcher)`` on Esc and ``on_text(watcher, typed)`` once typing starts.

    A no-op off a TTY or on Windows.
    """

    def __init__(
        self, on_esc: Callable[[EscWatcher], None], on_text: Callable[[EscWatcher, str], None] | None = None
    ) -> None:
        self._on_esc = on_esc
        self._on_text = on_text
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

    def edit_line(self, prompt: str, prompt_cells: int, text: str = "", *, erase: bool = False) -> str | None:
        """The line typed after ``prompt`` from ``text``; None on esc, ctrl+d, or once abandoned (the turn ended)."""
        assert self._fd is not None
        decode = codecs.getincrementaldecoder("utf-8")(errors="ignore").decode
        rows = self._draw(prompt, prompt_cells, text, 1)
        result: str | None = None
        while not self._abandoned.is_set():
            ready, _, _ = select.select([self._fd], [], [], _POLL_S)
            if not ready:
                continue
            chunk = decode(os.read(self._fd, 1024))
            if chunk == "\x1b" or (chunk == "\x04" and not text):
                break
            done = False
            for char in chunk:
                if char in "\r\n":
                    done = True
                    break
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
            rows = self._draw(prompt, prompt_cells, text, rows)
            if done:
                result = text
                break
        if erase:
            sys.stderr.write(_UP_CLEARING * (rows - 1) + "\r\x1b[J")
            sys.stderr.flush()
        return None if self._abandoned.is_set() else result

    def _draw(self, prompt: str, prompt_cells: int, text: str, rows: int) -> int:
        """Redraw the line from its first row; it may wrap, and backspace can't cross a wrap."""
        sys.stderr.write(_UP_CLEARING * (rows - 1) + "\r\x1b[J" + prompt + text)
        sys.stderr.flush()
        width = max(1, os.get_terminal_size(self._fd).columns) if self._fd is not None else 80
        return max(1, -(-(prompt_cells + cell_len(text)) // width))

    def _run(self) -> None:
        assert self._fd is not None
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], _POLL_S)
            if not ready:
                continue
            chunk = os.read(self._fd, 1024)
            typed = chunk.decode(errors="ignore")
            if chunk == ESC:
                self._on_esc(self)
            elif self._on_text is not None and typed and typed[0].isprintable():
                self._on_text(self, typed)

    def _restore(self) -> None:
        if self._fd is not None and self._saved is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

"""Interactive prompt: saved history, a live slash-command menu, a state toolbar, and Claude Code style keys."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.styles import Style

from hai_agents_cli import ui

SHORTCUTS = "?"
EXIT_WINDOW_S = 2.0

Rows = Callable[[], list[tuple[str, str]]]

_STYLE = Style.from_dict(
    {
        "prompt": ui.IRIS,
        "placeholder": "#6c6c6c",
        "bottom-toolbar": "noreverse #8a8a8a",
        "bottom-toolbar.warn": "noreverse #d7af00",
        "completion-menu.completion": "bg:default #bcbcbc",
        "completion-menu.completion.current": f"bg:default {ui.IRIS} bold",
        "completion-menu.meta.completion": "bg:default #6c6c6c",
        "completion-menu.meta.completion.current": "bg:default #8a8a8a",
    }
)


class _SlashCompleter(Completer):
    def __init__(self, commands: Rows) -> None:
        self._commands = commands

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for usage, description in self._commands():
            name = usage.split()[0]
            if name.startswith(text):
                yield Completion(name, start_position=-len(text), display=usage, display_meta=description)


class Prompt:
    """One prompt per conversation; `read` returns the submitted text, or None when the user leaves."""

    def __init__(self, history_path: Path, commands: Rows) -> None:
        history_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._commands = commands
        self._exit_armed_at = 0.0
        self._session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            completer=_SlashCompleter(commands),
            complete_while_typing=True,
            key_bindings=self._key_bindings(),
            style=_STYLE,
            multiline=True,
            prompt_continuation="  ",
        )

    def read(self, *, toolbar: Callable[[], str], placeholder: str) -> str | None:
        def bottom() -> FormattedText:
            if self._exit_pending():
                return FormattedText([("class:bottom-toolbar.warn", "  press ctrl+c again to exit")])
            return FormattedText([("", toolbar())])

        try:
            return self._session.prompt(
                FormattedText([("class:prompt", f"{ui.PROMPT} ")]),
                bottom_toolbar=bottom,
                placeholder=FormattedText([("class:placeholder", placeholder)]),
                refresh_interval=0.5,
            )
        except (EOFError, KeyboardInterrupt):
            return None

    def _first_command(self, prefix: str) -> str | None:
        names = [usage.split()[0] for usage, _ in self._commands()]
        return next((name for name in names if name.startswith(prefix)), None)

    def _exit_pending(self) -> bool:
        return time.monotonic() - self._exit_armed_at < EXIT_WINDOW_S

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        empty = Condition(lambda: not self._session.default_buffer.text)

        @kb.add("enter")
        def _submit(event: KeyPressEvent) -> None:
            buf = event.current_buffer
            if not buf.text.strip():
                return
            if buf.document.text_before_cursor.endswith("\\"):
                buf.delete_before_cursor()
                buf.newline(copy_margin=False)
                return
            if buf.text.startswith("/") and " " not in buf.text:
                picked = buf.complete_state.current_completion if buf.complete_state else None
                name = picked.text if picked else self._first_command(buf.text)
                if name:
                    buf.text = name
            buf.validate_and_handle()

        @kb.add("escape", "enter")
        @kb.add("c-j")
        def _newline(event: KeyPressEvent) -> None:
            event.current_buffer.newline(copy_margin=False)

        @kb.add("c-c")
        def _interrupt(event: KeyPressEvent) -> None:
            buf = event.current_buffer
            if buf.text:
                buf.reset()
                self._exit_armed_at = 0.0
            elif self._exit_pending():
                event.app.exit(result=None)
            else:
                self._exit_armed_at = time.monotonic()
                event.app.invalidate()

        @kb.add("c-d", filter=empty)
        def _leave(event: KeyPressEvent) -> None:
            event.app.exit(result=None)

        @kb.add(SHORTCUTS, filter=empty)
        def _shortcuts(event: KeyPressEvent) -> None:
            event.current_buffer.text = SHORTCUTS
            event.current_buffer.validate_and_handle()

        return kb

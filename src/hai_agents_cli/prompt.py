"""Interactive prompt: saved history, a live slash-command menu, a state toolbar, and Claude Code style keys."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition, is_searching, to_filter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style

from hai_agents_cli import ui

SHORTCUTS = "?"
EXIT_WINDOW_S = 2.0

Rows = Callable[[], list[tuple[str, str]]]

_STYLE = Style.from_dict(
    {
        "prompt": ui.IRIS,
        "rule": f"noreverse {ui.RULE}",
        "placeholder": "#6c6c6c",
        "bottom-toolbar": "noreverse #8a8a8a",
        "bottom-toolbar.warn": "noreverse #d7af00",
        "slash": "#bcbcbc",
        "slash.current": f"{ui.IRIS} bold",
        "slash.meta": "#6c6c6c",
        "slash.meta.current": ui.IRIS,
        "slash.header": f"{ui.IRIS} bold",
    }
)

PICKER_HEIGHT = 12


def _rule() -> str:
    return "─" * get_app().output.get_size().columns


def choose(rows: Sequence[tuple[str, str]], headers: Mapping[int, str] | None = None, current: int = 0) -> int | None:
    """Pick a row with the arrow keys; None when cancelled. ``headers`` titles the section starting at a row."""
    headers = headers or {}
    state = {"current": current, "lines": [0] * len(rows)}

    def render() -> FormattedText:
        fragments: list[tuple[str, str]] = []
        line = 0
        for index, (label, meta) in enumerate(rows):
            if index in headers:
                if index:
                    fragments.append(("", "\n"))
                    line += 1
                fragments.append(("class:slash.header", f"  {headers[index]}\n"))
                line += 1
            state["lines"][index] = line
            suffix, marker = (".current", "›") if index == state["current"] else ("", " ")
            fragments += [(f"class:slash{suffix}", f"{marker} {label}"), (f"class:slash.meta{suffix}", f"  {meta}")]
            fragments.append(("", "\n"))
            line += 1
        return FormattedText(fragments)

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("s-tab")
    def _up(event: KeyPressEvent) -> None:
        state["current"] = (state["current"] - 1) % len(rows)

    @kb.add("down")
    @kb.add("tab")
    def _down(event: KeyPressEvent) -> None:
        state["current"] = (state["current"] + 1) % len(rows)

    @kb.add("enter")
    def _pick(event: KeyPressEvent) -> None:
        event.app.exit(result=state["current"])

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    listing = FormattedTextControl(
        render,
        focusable=True,
        show_cursor=False,
        get_cursor_position=lambda: Point(0, state["lines"][state["current"]]),
    )
    hint = FormattedTextControl(FormattedText([("class:slash.meta", "  ↑↓ move · enter picks · esc cancels")]))
    layout = Layout(HSplit([Window(listing, height=Dimension(max=PICKER_HEIGHT)), Window(hint, height=1)]))
    app: Application[int | None] = Application(
        layout=layout, key_bindings=kb, style=_STYLE, full_screen=False, erase_when_done=True
    )
    return app.run()


class _SlashMenu:
    """The commands matching a typed `/prefix`, listed under the input with one row selected."""

    def __init__(self, commands: Rows) -> None:
        self._commands = commands
        self._index, self._typed = 0, ""

    def matches(self, text: str) -> list[tuple[str, str]]:
        if not text.startswith("/") or any(char.isspace() for char in text):
            return []
        return [(usage, about) for usage, about in self._commands() if usage.split()[0].startswith(text)]

    def selected(self, text: str) -> str | None:
        rows = self.matches(text)
        return rows[self._current(text, rows)][0] if rows else None

    def move(self, text: str, step: int) -> None:
        rows = self.matches(text)
        if rows:
            self._index, self._typed = (self._current(text, rows) + step) % len(rows), text

    def render(self, text: str) -> FormattedText:
        rows = self.matches(text)
        current = self._current(text, rows)
        width = max(len(usage) for usage, _ in rows)
        fragments: list[tuple[str, str]] = []
        for index, (usage, about) in enumerate(rows):
            suffix = ".current" if index == current else ""
            if fragments:
                fragments.append(("", "\n"))
            fragments += [(f"class:slash{suffix}", f"  {usage.ljust(width)}   "), (f"class:slash.meta{suffix}", about)]
        return FormattedText(fragments)

    def _current(self, text: str, rows: list[tuple[str, str]]) -> int:
        return min(self._index, len(rows) - 1) if text == self._typed else 0


class Prompt:
    """One prompt per conversation; `read` returns the submitted text, or None when the user leaves."""

    def __init__(self, history_path: Path, commands: Rows) -> None:
        self._menu = _SlashMenu(commands)
        self._exit_armed_at = 0.0
        self._example: str | None = None
        self._session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=AutoSuggestFromHistory(),
            key_bindings=self._key_bindings(),
            style=_STYLE,
            multiline=True,
            prompt_continuation="  ",
            erase_when_done=True,
        )
        # The input grows with its text only, so the toolbar and menu sit right under it.
        self._session.layout.current_window.dont_extend_height = to_filter(True)

    def read(
        self, *, toolbar: Callable[[], str], placeholder: str, example: str | None = None, default: str = ""
    ) -> str | None:
        """``example`` is the task a placeholder suggests; tab types it. ``default`` prefills the input."""
        self._example = example

        def message() -> FormattedText:
            return FormattedText([("class:rule", _rule() + "\n"), ("class:prompt", f"{ui.PROMPT} ")])

        def bottom() -> FormattedText:
            rule = [("class:rule", _rule() + "\n")]
            if self._exit_pending():
                return FormattedText([*rule, ("class:bottom-toolbar.warn", "  press ctrl+c again to exit")])
            text = self._menu_text()
            if self._menu.matches(text):
                return FormattedText([*rule, *self._menu.render(text)])
            return FormattedText([*rule, ("", toolbar())])

        try:
            return self._session.prompt(
                message,
                bottom_toolbar=bottom,
                placeholder=FormattedText([("class:placeholder", placeholder)]),
                refresh_interval=0.5,
                default=default,
            )
        except (EOFError, KeyboardInterrupt):
            return None

    def _menu_text(self) -> str:
        """Empty while browsing history, so up and down keep scrolling past recalled commands."""
        buf = self._session.default_buffer
        return buf.text if buf.working_index == len(buf._working_lines) - 1 else ""

    def _exit_pending(self) -> bool:
        return time.monotonic() - self._exit_armed_at < EXIT_WINDOW_S

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        empty = Condition(lambda: not self._session.default_buffer.text)
        menu_open = Condition(lambda: bool(self._menu.matches(self._menu_text())))

        @kb.add("enter", filter=~is_searching)
        def _submit(event: KeyPressEvent) -> None:
            buf = event.current_buffer
            if not buf.text.strip():
                return
            if buf.document.text_before_cursor.endswith("\\"):
                buf.delete_before_cursor()
                buf.newline(copy_margin=False)
                return
            usage = self._menu.selected(self._menu_text())
            if usage:
                buf.text = usage.split()[0]
            buf.validate_and_handle()

        @kb.add("up", filter=menu_open)
        @kb.add("s-tab", filter=menu_open)
        def _menu_up(event: KeyPressEvent) -> None:
            self._menu.move(event.current_buffer.text, -1)

        @kb.add("down", filter=menu_open)
        def _menu_down(event: KeyPressEvent) -> None:
            self._menu.move(event.current_buffer.text, 1)

        @kb.add("tab", filter=menu_open)
        def _menu_complete(event: KeyPressEvent) -> None:
            usage = self._menu.selected(event.current_buffer.text) or ""
            name, _, args = usage.partition(" ")
            event.current_buffer.text = f"{name} " if args else name
            event.current_buffer.cursor_position = len(event.current_buffer.text)

        @kb.add("tab", filter=~menu_open)
        def _accept_suggestion(event: KeyPressEvent) -> None:
            buf = event.current_buffer
            suggestion = buf.suggestion or (buf.auto_suggest and buf.auto_suggest.get_suggestion(buf, buf.document))
            if suggestion and buf.document.is_cursor_at_the_end:
                buf.insert_text(suggestion.text)
            elif not buf.text and self._example:
                buf.insert_text(self._example)

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

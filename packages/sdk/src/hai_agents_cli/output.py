"""Dual-mode rendering: human-friendly Rich on a TTY, JSON when piped or forced.

Data goes to stdout; status, notes, and errors go to stderr, so JSON consumers
get a clean stream.
"""

from __future__ import annotations

import contextlib
import enum
import json
import sys
import typing
from dataclasses import dataclass

from rich.console import Console


class OutputMode(str, enum.Enum):
    AUTO = "auto"
    JSON = "json"


def to_jsonable(obj: typing.Any) -> typing.Any:
    """Best-effort conversion of SDK pydantic models (and containers) to plain JSON."""
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_jsonable(value) for key, value in obj.items()}
    value = getattr(obj, "value", None)
    if isinstance(obj, enum.Enum) and value is not None:
        return value
    return obj


@dataclass
class Output:
    mode: OutputMode
    quiet: bool
    out: Console
    err: Console

    @classmethod
    def create(cls, mode: OutputMode, quiet: bool, no_color: bool) -> "Output":
        return cls(
            mode=mode,
            quiet=quiet,
            out=Console(file=sys.stdout, no_color=no_color, highlight=False),
            err=Console(file=sys.stderr, no_color=no_color, highlight=False),
        )

    @property
    def json_mode(self) -> bool:
        if self.mode is OutputMode.JSON:
            return True
        # Key off the raw fd, not Rich's is_terminal: FORCE_COLOR/CI flip the latter
        # to True even when piped, which would leak tables into a JSON consumer.
        return not sys.stdout.isatty()

    def print_json(self, data: typing.Any) -> None:
        print(json.dumps(to_jsonable(data), indent=2, default=str), file=sys.stdout)

    def render(self, model: typing.Any, view: typing.Any = None) -> None:
        """Emit JSON when piped/forced, otherwise the provided Rich view (or pretty JSON)."""
        if self.json_mode or view is None:
            if self.json_mode:
                self.print_json(model)
            else:
                self.out.print_json(json.dumps(to_jsonable(model), default=str))
        elif getattr(view, "row_count", None) == 0:
            self.note("[dim]Nothing to show.[/dim]")
        else:
            self.out.print(view)

    def note(self, message: str) -> None:
        if not self.quiet and not self.json_mode:
            self.err.print(message)

    def fail(self, kind: str, message: str, status: int | None = None) -> None:
        """Report an error on stderr: structured JSON in json mode, human text otherwise."""
        if self.json_mode:
            error: dict[str, typing.Any] = {"kind": kind, "message": message}
            if status is not None:
                error["status"] = status
            print(json.dumps({"error": error}), file=sys.stderr)
        else:
            label = f"error {status}" if status is not None else "error"
            self.err.print(f"[red]{label}:[/red] {message}")

    def status(self, message: str) -> typing.ContextManager:
        if self.json_mode or self.quiet or not self.err.is_terminal:
            return contextlib.nullcontext()
        return self.err.status(message, spinner="dots")

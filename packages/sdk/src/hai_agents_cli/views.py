"""Rich table and event renderers for human-facing output."""

from __future__ import annotations

import datetime as dt
import typing

from rich.table import Table
from rich.text import Text

_STATUS_STYLES = {
    "completed": "green",
    "running": "cyan",
    "pending": "yellow",
    "paused": "yellow",
    "idle": "blue",
    "failed": "red",
    "timed_out": "red",
    "interrupted": "red",
}


def _str(value: typing.Any) -> str:
    if value is None:
        return ""
    value = getattr(value, "value", value)
    if isinstance(value, dt.datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value)


def _status_text(status: typing.Any) -> Text:
    label = _str(status)
    return Text(label, style=_STATUS_STYLES.get(label, "white"))


def _table(*columns: str) -> Table:
    table = Table(show_edge=False, header_style="bold", expand=False, pad_edge=False)
    for column in columns:
        table.add_column(column)
    return table


def sessions_table(items: typing.Iterable[typing.Any]) -> Table:
    table = _table("ID", "STATUS", "AGENT", "CREATED")
    for item in items:
        table.add_row(
            _str(getattr(item, "id", "")),
            _status_text(getattr(item, "status", None)),
            _str(getattr(item, "agent", "")),
            _str(getattr(item, "created_at", "")),
        )
    return table


def agents_table(items: typing.Iterable[typing.Any]) -> Table:
    table = _table("NAME", "MODEL", "DESCRIPTION")
    for item in items:
        table.add_row(
            _str(getattr(item, "name", "")), _str(getattr(item, "model", "")), _str(getattr(item, "description", ""))
        )
    return table


def skills_table(items: typing.Iterable[typing.Any]) -> Table:
    table = _table("NAME", "SOURCE", "DESCRIPTION")
    for item in items:
        table.add_row(
            _str(getattr(item, "name", "")), _str(getattr(item, "source", "")), _str(getattr(item, "description", ""))
        )
    return table


def environments_table(items: typing.Iterable[typing.Any]) -> Table:
    table = _table("ID", "KIND", "MODE", "SIZE")
    for item in items:
        size = f"{_str(getattr(item, 'width', ''))}x{_str(getattr(item, 'height', ''))}"
        table.add_row(
            _str(getattr(item, "id", "")),
            _str(getattr(item, "kind", "")),
            _str(getattr(item, "mode", "")),
            size if size != "x" else "",
        )
    return table


def events_table(events: typing.Iterable[typing.Any]) -> Table:
    table = _table("#", "TIME", "TYPE")
    for index, event in enumerate(events):
        table.add_row(str(index), _str(getattr(event, "timestamp", "")), _str(getattr(event, "type", "")))
    return table


def event_line(index: int, event: typing.Any) -> Text:
    timestamp = getattr(event, "timestamp", None)
    stamp = timestamp.astimezone().strftime("%H:%M:%S") if isinstance(timestamp, dt.datetime) else ""
    line = Text()
    line.append(f"{stamp} ", style="dim")
    line.append(f"#{index} ", style="dim")
    line.append(_str(getattr(event, "type", "event")), style="bold cyan")
    return line

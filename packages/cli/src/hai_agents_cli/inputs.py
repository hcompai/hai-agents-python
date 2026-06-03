"""Helpers for reading structured input from flags, files, or stdin."""

from __future__ import annotations

import json
import sys
import typing

import typer


def load_json(value: str) -> dict[str, typing.Any]:
    """Parse a JSON object from an inline string, ``@path`` file, or ``-`` (stdin)."""
    if value == "-":
        raw = sys.stdin.read()
    elif value.startswith("@"):
        with open(value[1:], encoding="utf-8") as fh:
            raw = fh.read()
    else:
        raw = value
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise typer.BadParameter(f"invalid JSON: {err}") from err
    if not isinstance(parsed, dict):
        raise typer.BadParameter("expected a JSON object.")
    return parsed

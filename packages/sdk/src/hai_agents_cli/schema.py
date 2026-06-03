"""Machine-readable description of the command tree, so agents discover the CLI
without scraping --help text."""

from __future__ import annotations

import typing


def _describe_param(param: typing.Any) -> dict[str, typing.Any]:
    return {
        "name": param.name,
        "flags": list(param.opts),
        "kind": param.param_type_name,
        "type": getattr(param.type, "name", "text"),
        "required": bool(param.required),
        "is_flag": bool(getattr(param, "is_flag", False)),
        "help": getattr(param, "help", None),
    }


def describe(command: typing.Any, name: str) -> dict[str, typing.Any]:
    """Recursively describe a Click command (from ``typer.main.get_command``) and its subcommands."""
    node: dict[str, typing.Any] = {"name": name, "help": command.help or command.short_help or ""}
    params = [_describe_param(p) for p in command.params if p.name != "help"]
    if params:
        node["params"] = params
    subcommands = getattr(command, "commands", None)
    if subcommands:
        node["commands"] = [describe(sub, sub_name) for sub_name, sub in sorted(subcommands.items())]
    return node

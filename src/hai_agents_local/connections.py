"""The MCP servers this machine's agents reach: ``mcp.json`` beside the stored credentials, in Cursor's format."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from hai_agents.client import credentials_path

logger = logging.getLogger(__name__)

Transport = Literal["stdio", "http", "sse"]

# `mcporter call <name>.<tool>` splits on the first dot.
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REFERENCE = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")


def connections_path() -> Path:
    return credentials_path().with_name("mcp.json")


@dataclass(frozen=True)
class Connection:
    """One MCP server: a URL with its headers, or a command this machine starts."""

    name: str
    transport: Transport
    url: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: str | None = None
    variables: frozenset[str] = frozenset()
    """The environment variables its `${VAR}` references read: keys, to keep from the agent's shell."""


def read_servers(path: Path) -> dict[str, Any]:
    """The `mcpServers` object of an MCP config file; empty where the file does not exist."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise ValueError(f"{path} holds no `mcpServers` object")
    return servers


def save_servers(servers: Mapping[str, Any], path: Path | None = None) -> Path:
    """Write `servers` as the file's `mcpServers`, keeping its other keys; owner-only, as it holds keys."""
    path = path or connections_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.tmp")
    staged.unlink(missing_ok=True)
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump({**data, "mcpServers": dict(servers)}, file, indent=2)
        file.write("\n")
    os.replace(staged, path)
    return path


def check_name(name: str) -> None:
    if not _NAME.match(name):
        raise ValueError(
            f"{name!r}: a name holds 1 to 64 letters, digits, `-` and `_`, as `mcporter call <name>.<tool>` reads it"
        )


def load_connections(path: Path | None = None) -> list[Connection]:
    """Each server in the file, its `${VAR}` filled from the environment, else the stored credentials.

    A server that names no `url` or `command`, or a variable set nowhere, is left out with a warning."""
    path = path or connections_path()
    servers = read_servers(path)
    if not servers:
        return []
    values = {**_stored_values(), **os.environ}
    connections = []
    for name, spec in servers.items():
        try:
            connections.append(_connection(name, spec, values))
        except ValueError as error:
            logger.warning("MCP server %r in %s is left out: %s", name, path, error)
    return connections


def _connection(name: str, spec: object, values: Mapping[str, str]) -> Connection:
    check_name(name)
    if not isinstance(spec, dict):
        raise ValueError("it is not an object")
    read: set[str] = set()

    def filled(text: object) -> str:
        def value(match: re.Match[str]) -> str:
            if match[1] not in values:
                raise ValueError(f"it needs {match[1]}, set neither in the environment nor in {credentials_path()}")
            read.add(match[1])
            return values[match[1]]

        return _REFERENCE.sub(value, str(text))

    def table(key: str) -> dict[str, str]:
        found = spec.get(key) or {}
        if not isinstance(found, dict):
            raise ValueError(f"`{key}` is not an object")
        return {str(item): filled(text) for item, text in found.items()}

    kind = spec.get("type") or spec.get("transport")
    if url := spec.get("url"):
        transport: Transport = "sse" if kind == "sse" else "http"
        connection = Connection(name, transport, url=filled(url), headers=table("headers"))
    elif command := spec.get("command"):
        args = spec.get("args") or []
        if not isinstance(args, list):
            raise ValueError("`args` is not a list")
        cwd = spec.get("cwd")
        connection = Connection(
            name,
            "stdio",
            command=os.path.expanduser(filled(command)),
            args=tuple(filled(arg) for arg in args),
            env=table("env"),
            cwd=os.path.expanduser(filled(cwd)) if cwd else None,
        )
    else:
        raise ValueError("it names neither a `url` nor a `command`")
    return replace(connection, variables=frozenset(read))


def _stored_values() -> dict[str, str]:
    stored = credentials_path()
    if not stored.exists():
        return {}
    from dotenv import dotenv_values

    return {name: value for name, value in dotenv_values(stored).items() if value is not None}

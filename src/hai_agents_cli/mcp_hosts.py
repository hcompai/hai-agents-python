"""MCP client registry + install dispatch for the remote `hai-agents` server. Add a client = add one `Client`."""

from __future__ import annotations

import enum
import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SERVER_NAME = "hai-agents"
DEFAULT_MCP_URL = "https://agp.eu.hcompany.ai/mcp"

# Placeholders kept in the registry leaves; substituted with the live endpoint + key at wire time.
_URL = "__MCP_URL__"
_KEY = "__MCP_KEY__"


def _bearer_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_KEY}"}


class Status(enum.Enum):
    """Outcome of one install step."""

    INSTALLED = "installed"
    SKIPPED = "skipped"
    ABSENT = "absent"
    FAILED = "failed"

    @property
    def ok(self) -> bool:
        return self in (Status.INSTALLED, Status.SKIPPED)

    @property
    def fatal(self) -> bool:
        return self is Status.FAILED


@dataclass(frozen=True)
class Client:
    """One MCP client: CLI clients set `cli_cmd`; file clients set `config_path` + `key_path` + `leaf`."""

    name: str
    config_path: str | None = None
    cli_cmd: tuple[str, ...] | None = None
    cli_remove_cmd: tuple[str, ...] | None = None
    key_path: tuple[str, ...] | None = None
    leaf: dict[str, Any] | None = None
    skills_dir: str | None = None  # under $HOME; None if the client has no SKILL.md auto-load


def _vscode_config_path(app_dir: str) -> str:
    """Per-OS user-level VS Code MCP config for the given app directory (`Code`, `Code - Insiders`)."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return str(Path(appdata) / app_dir / "User" / "mcp.json")
    if system == "Darwin":
        return f"~/Library/Application Support/{app_dir}/User/mcp.json"
    xdg = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return f"{xdg}/{app_dir}/User/mcp.json"


CLIENTS: dict[str, Client] = {
    "cursor": Client(
        name="Cursor",
        config_path="~/.cursor/mcp.json",
        key_path=("mcpServers", SERVER_NAME),
        leaf={"url": _URL, "headers": _bearer_headers()},
        skills_dir=".cursor/skills",
    ),
    "vscode": Client(
        name="VS Code",
        config_path=_vscode_config_path("Code"),
        key_path=("servers", SERVER_NAME),
        leaf={"type": "http", "url": _URL, "headers": _bearer_headers()},
    ),
    "vscode-insiders": Client(
        name="VS Code Insiders",
        config_path=_vscode_config_path("Code - Insiders"),
        key_path=("servers", SERVER_NAME),
        leaf={"type": "http", "url": _URL, "headers": _bearer_headers()},
    ),
    "claude-code": Client(
        name="Claude Code",
        cli_cmd=(
            "claude",
            "mcp",
            "add",
            "--scope",
            "user",
            "--transport",
            "http",
            SERVER_NAME,
            _URL,
            "--header",
            f"Authorization: Bearer {_KEY}",
        ),
        cli_remove_cmd=("claude", "mcp", "remove", "--scope", "user", SERVER_NAME),
        skills_dir=".claude/skills",
    ),
    "windsurf": Client(
        name="Windsurf",
        config_path="~/.codeium/windsurf/mcp_config.json",
        key_path=("mcpServers", SERVER_NAME),
        leaf={"serverUrl": _URL, "headers": _bearer_headers()},
    ),
}


def resolve_mcp_url(base_url: str | None, override: str | None) -> str:
    """MCP endpoint: explicit override, else the base URL's origin + `/mcp`, else the EU host."""
    if override:
        return override
    if base_url:
        parts = urlsplit(base_url)
        if parts.scheme and parts.netloc:
            return urlunsplit((parts.scheme, parts.netloc, "/mcp", "", ""))
    return DEFAULT_MCP_URL


def host_present(c: Client) -> bool:
    """True if the client looks installed: its CLI is on PATH, or its config directory exists."""
    if c.cli_cmd is not None:
        return shutil.which(c.cli_cmd[0]) is not None
    assert c.config_path is not None
    path = Path(c.config_path).expanduser()
    return path.exists() or path.parent.exists()


def host_target(c: Client) -> str:
    """Where the config lands (~-path), or 'via CLI' for CLI-managed clients."""
    return _home_short(c.config_path) if c.config_path else "via CLI"


def wire_skill(c: Client) -> tuple[Status, str]:
    """Symlink the bundled hai-agents SKILL.md into `c`'s skills dir so the host auto-loads it."""
    if c.skills_dir is None:
        return Status.SKIPPED, "no skill auto-load"
    home = Path.home()
    if not (home / PurePosixPath(c.skills_dir).parts[0]).exists():
        return Status.ABSENT, "client not installed"
    skills_root = home / c.skills_dir
    skills_root.mkdir(parents=True, exist_ok=True)
    link = skills_root / SERVER_NAME
    source = Path(str(resources.files("hai_agents_cli.host_skills").joinpath(SERVER_NAME)))
    if link.is_symlink():
        # strict=False: a reinstall can leave the link dangling at a removed site-packages path.
        if link.resolve(strict=False) == source.resolve(strict=False):
            return Status.SKIPPED, _home_short(str(link))
        link.unlink()
    elif link.exists():
        skill_md, src_md = link / "SKILL.md", source / "SKILL.md"
        is_ours = link.is_dir() and skill_md.exists()
        if is_ours and src_md.exists() and skill_md.read_bytes() == src_md.read_bytes():
            return Status.SKIPPED, _home_short(str(link))
        if not is_ours:
            return Status.FAILED, f"{_home_short(str(link))} exists and is not a hai-agents skill"
        shutil.rmtree(link)
    try:
        link.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        # Windows without Developer Mode can't symlink; mirror the tree as a fallback.
        if os.name == "nt":
            try:
                shutil.copytree(source, link)
            except OSError as copy_exc:
                return Status.FAILED, f"{link}: {copy_exc}"
            return Status.INSTALLED, f"{_home_short(str(link))} (copy; enable Developer Mode for symlinks)"
        return Status.FAILED, f"{link}: {exc}"
    return Status.INSTALLED, _home_short(str(link))


def wire_mcp(c: Client, url: str, key: str) -> tuple[Status, str]:
    """Install the server into `c`: a CLI `add`, or a JSON config merge."""
    if c.cli_cmd is not None:
        add = [_render(arg, url, key) for arg in c.cli_cmd]
        remove = list(c.cli_remove_cmd) if c.cli_remove_cmd else None
        return _install_via_cli(add, remove)
    assert c.config_path is not None and c.key_path is not None and c.leaf is not None
    return _wire_json(Path(c.config_path).expanduser(), c.key_path, _render(c.leaf, url, key))


def _render(obj: Any, url: str, key: str) -> Any:
    """Deep-copy `obj`, substituting the URL and key placeholders in every string."""
    if isinstance(obj, str):
        return obj.replace(_URL, url).replace(_KEY, key)
    if isinstance(obj, dict):
        return {k: _render(v, url, key) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_render(x, url, key) for x in obj]
    return obj


def _install_via_cli(add_cmd: list[str], remove_cmd: list[str] | None = None) -> tuple[Status, str]:
    exe = shutil.which(add_cmd[0])
    if exe is None:
        return Status.ABSENT, f"{add_cmd[0]!r} not on PATH"
    # `add` refuses to overwrite, so drop any existing entry first; otherwise a rotated key or
    # changed url is silently kept. Re-adding always reflects the current url + key.
    if remove_cmd is not None:
        subprocess.run([exe, *remove_cmd[1:]], capture_output=True, text=True, check=False)
    try:
        subprocess.run([exe, *add_cmd[1:]], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return Status.FAILED, (exc.stderr or exc.stdout or str(exc)).strip()
    return Status.INSTALLED, f"via {add_cmd[0]} CLI"


def _wire_json(path: Path, key_path: tuple[str, ...], leaf: dict[str, Any]) -> tuple[Status, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists() and path.stat().st_size > 0:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return Status.FAILED, f"{path}: invalid JSON ({exc})"
        if not isinstance(loaded, dict):
            return Status.FAILED, f"{path}: top-level is not an object"
        data = loaded
    cursor: Any = data
    for k in key_path[:-1]:
        cursor = cursor.setdefault(k, {})
        if not isinstance(cursor, dict):
            return Status.FAILED, f"{path}: {k!r} is not an object"
    last = key_path[-1]
    if cursor.get(last) == leaf:
        return Status.SKIPPED, _home_short(str(path))
    cursor[last] = leaf
    _atomic_write_secret(path, json.dumps(data, indent=2) + "\n")
    return Status.INSTALLED, _home_short(str(path))


def _atomic_write_secret(path: Path, content: str) -> None:
    """Write to a sibling temp then `rename` over the target, chmod 600 (the file embeds an API key)."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _home_short(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home) :] if p.startswith(home) else p

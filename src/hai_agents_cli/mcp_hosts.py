"""MCP host registry for the remote `hai-agents` server, plus the install engine other CLIs reuse with their own registry."""

from __future__ import annotations

import enum
import json
import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SERVER_NAME = "hai-agents"
DEFAULT_MCP_URL = "https://agp.eu.hcompany.ai/mcp"

# Placeholders kept in the registry leaves; substituted with the live endpoint + key at wire time.
URL = "__MCP_URL__"
KEY = "__MCP_KEY__"
_BEARER_HEADERS = {"Authorization": f"Bearer {KEY}"}


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
    """One MCP host: CLI hosts set `cli_cmd`; file hosts set `config_path` (JSON or YAML) + `key_path` + `leaf`."""

    name: str
    config_path: str | None = None
    cli_cmd: tuple[str, ...] | None = None
    cli_remove_cmds: tuple[tuple[str, ...], ...] = ()
    key_path: tuple[str, ...] | None = None
    leaf: dict[str, Any] | None = None
    skills_dir: str | None = None  # under $HOME; None if the host has no SKILL.md auto-load
    home_marker: str | None = None  # under $HOME; its presence proves the host is installed


def user_config_path(*parts: str) -> str:
    """Per-OS user app config: %APPDATA% on Windows, ~/Library/Application Support on macOS, else $XDG_CONFIG_HOME."""
    system = platform.system()
    if system == "Windows":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif system == "Darwin":
        root = "~/Library/Application Support"
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return str(Path(root, *parts))


CLIENTS: dict[str, Client] = {
    "cursor": Client(
        name="Cursor",
        config_path="~/.cursor/mcp.json",
        key_path=("mcpServers", SERVER_NAME),
        leaf={"url": URL, "headers": _BEARER_HEADERS},
        skills_dir=".cursor/skills",
    ),
    "vscode": Client(
        name="VS Code",
        config_path=user_config_path("Code", "User", "mcp.json"),
        key_path=("servers", SERVER_NAME),
        leaf={"type": "http", "url": URL, "headers": _BEARER_HEADERS},
    ),
    "vscode-insiders": Client(
        name="VS Code Insiders",
        config_path=user_config_path("Code - Insiders", "User", "mcp.json"),
        key_path=("servers", SERVER_NAME),
        leaf={"type": "http", "url": URL, "headers": _BEARER_HEADERS},
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
            URL,
            "--header",
            f"Authorization: Bearer {KEY}",
        ),
        cli_remove_cmds=(
            # Clear any prior entry at either writable scope so a rotated key / url can't survive,
            # and a narrower local entry can't shadow the user-scoped one we install.
            ("claude", "mcp", "remove", "--scope", "local", SERVER_NAME),
            ("claude", "mcp", "remove", "--scope", "user", SERVER_NAME),
        ),
        skills_dir=".claude/skills",
    ),
    "hermes": Client(
        name="Hermes",
        config_path="~/.hermes/config.yaml",
        key_path=("mcp_servers", SERVER_NAME),
        leaf={"url": URL, "headers": _BEARER_HEADERS},
    ),
    "windsurf": Client(
        name="Windsurf",
        config_path="~/.codeium/windsurf/mcp_config.json",
        key_path=("mcpServers", SERVER_NAME),
        leaf={"serverUrl": URL, "headers": _BEARER_HEADERS},
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


def bundled_skill() -> Path:
    """The hai-agents SKILL.md directory shipped with this package."""
    return Path(str(resources.files("hai_agents_cli.host_skills").joinpath(SERVER_NAME)))


def host_present(c: Client) -> bool:
    """True if the host looks installed: its home marker exists, its CLI is on PATH, or its config directory exists."""
    if c.home_marker and (Path.home() / c.home_marker).exists():
        return True
    if c.cli_cmd is not None:
        return shutil.which(c.cli_cmd[0]) is not None
    assert c.config_path is not None
    path = Path(c.config_path).expanduser()
    return path.exists() or path.parent.exists()


def host_target(c: Client) -> str:
    """Where the config lands (~-path), or 'via CLI' for CLI-managed hosts."""
    return home_short(c.config_path) if c.config_path else "via CLI"


def wire_skill(c: Client, name: str, source: Path) -> tuple[Status, str]:
    """Symlink the skill directory `source` into `c`'s skills dir as `name` so the host auto-loads it."""
    if c.skills_dir is None:
        return Status.SKIPPED, "no skill auto-load"
    home = Path.home()
    if not (home / (c.home_marker or PurePosixPath(c.skills_dir).parts[0])).exists():
        return Status.ABSENT, "host not installed"
    skills_root = home / c.skills_dir
    skills_root.mkdir(parents=True, exist_ok=True)
    link = skills_root / name
    if link.is_symlink():
        # strict=False: a reinstall can leave the link dangling at a removed site-packages path.
        if link.resolve(strict=False) == source.resolve(strict=False):
            return Status.SKIPPED, home_short(str(link))
        link.unlink()
    elif link.exists():
        skill_md, src_md = link / "SKILL.md", source / "SKILL.md"
        is_ours = link.is_dir() and skill_md.exists()
        if is_ours and src_md.exists() and skill_md.read_bytes() == src_md.read_bytes():
            return Status.SKIPPED, home_short(str(link))
        if not is_ours:
            return Status.FAILED, f"{home_short(str(link))} exists and is not a {name} skill"
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
            return Status.INSTALLED, f"{home_short(str(link))} (copy; enable Developer Mode for symlinks)"
        return Status.FAILED, f"{link}: {exc}"
    return Status.INSTALLED, home_short(str(link))


def wire_mcp(c: Client, substitutions: Mapping[str, str], *, secret: str | None = None) -> tuple[Status, str]:
    """Install the server into `c`, filling registry placeholders from `substitutions`; `secret` is masked in errors."""
    if c.cli_cmd is not None:
        add = [_render(arg, substitutions) for arg in c.cli_cmd]
        removes = [[_render(arg, substitutions) for arg in rm] for rm in c.cli_remove_cmds]
        return _install_via_cli(add, removes, secret=secret)
    assert c.config_path is not None and c.key_path is not None and c.leaf is not None
    return _wire_config(Path(c.config_path).expanduser(), c.key_path, _render(c.leaf, substitutions))


def _render(obj: Any, substitutions: Mapping[str, str]) -> Any:
    """Deep-copy `obj`, substituting every placeholder in every string."""
    if isinstance(obj, str):
        for placeholder, value in substitutions.items():
            obj = obj.replace(placeholder, value)
        return obj
    if isinstance(obj, dict):
        return {k: _render(v, substitutions) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_render(x, substitutions) for x in obj]
    return obj


def _install_via_cli(add_cmd: list[str], remove_cmds: list[list[str]], secret: str | None) -> tuple[Status, str]:
    exe = shutil.which(add_cmd[0])
    if exe is None:
        return Status.ABSENT, f"{add_cmd[0]!r} not on PATH"
    # `add` refuses to overwrite, so drop any existing entry first; otherwise a rotated key or
    # changed url is silently kept. Re-adding always reflects the current values.
    for rm in remove_cmds:
        subprocess.run([exe, *rm[1:]], capture_output=True, text=True, check=False)
    try:
        subprocess.run([exe, *add_cmd[1:]], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        # The CLI tends to echo the failing invocation (incl. the bearer header) back on stderr.
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        if secret:
            detail = detail.replace(secret, "***")
        return Status.FAILED, detail
    return Status.INSTALLED, f"via {add_cmd[0]} CLI"


def _wire_config(path: Path, key_path: tuple[str, ...], leaf: dict[str, Any]) -> tuple[Status, str]:
    """Merge `leaf` at `key_path` into a JSON or YAML config, keeping sibling servers and any keys the user added."""
    load: Callable[[str], Any]
    dump: Callable[[dict[str, Any]], str]
    parse_error: type[Exception]
    if path.suffix in (".yaml", ".yml"):
        import yaml

        load, parse_error = yaml.safe_load, yaml.YAMLError

        def dump(data: dict[str, Any]) -> str:
            return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)

    else:
        load, parse_error = json.loads, json.JSONDecodeError

        def dump(data: dict[str, Any]) -> str:
            return json.dumps(data, indent=2) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists() and path.stat().st_size > 0:
        try:
            loaded = load(path.read_text(encoding="utf-8"))
        except parse_error as exc:
            return Status.FAILED, f"{path}: invalid config ({exc})"
        # YAML reads an empty or comments-only file as None.
        if loaded is not None and not isinstance(loaded, dict):
            return Status.FAILED, f"{path}: top-level is not a mapping"
        data = loaded or {}
    cursor: Any = data
    for k in key_path[:-1]:
        cursor = cursor.setdefault(k, {})
        if not isinstance(cursor, dict):
            return Status.FAILED, f"{path}: {k!r} is not a mapping"
    last = key_path[-1]
    existing = cursor.get(last)
    merged = {**existing, **leaf} if isinstance(existing, dict) else leaf
    if existing == merged:
        return Status.SKIPPED, home_short(str(path))
    cursor[last] = merged
    if path.exists():
        # YAML round-trips drop comments; keep the original recoverable.
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    _atomic_write_secret(path, dump(data))
    return Status.INSTALLED, home_short(str(path))


def _atomic_write_secret(path: Path, content: str) -> None:
    """Write to a sibling temp then `rename` over the target, chmod 600 (the file may embed an API key)."""
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


def home_short(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home) :] if p.startswith(home) else p

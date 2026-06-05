"""MCP host registry + install/uninstall dispatch + skill auto-wire. Add a host = add one `Client`."""

from __future__ import annotations

import enum
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

SERVER_KEY = "hai"
MCP_BINARY = "hai-mcp"
SKILL_NAME = "hai-agents"


class Status(enum.Enum):
    """Outcome of one install/uninstall step."""

    INSTALLED = "installed"
    REMOVED = "removed"
    SKIPPED = "skipped"
    ABSENT = "absent"
    FAILED = "failed"

    @property
    def ok(self) -> bool:
        return self in (Status.INSTALLED, Status.REMOVED, Status.SKIPPED)

    @property
    def fatal(self) -> bool:
        return self is Status.FAILED


def home_short(p: Path | str) -> str:
    """Render `p` with $HOME collapsed to `~`."""
    s = str(p)
    home = str(Path.home())
    return "~" + s[len(home) :] if s.startswith(home) else s


def resolve_mcp_command() -> str:
    """Absolute path to `hai-mcp`, baked into host configs so GUI hosts hit it even with a stripped PATH."""
    venv_bin = str(Path(sys.executable).parent)
    found = shutil.which(MCP_BINARY, path=venv_bin) or shutil.which(MCP_BINARY)
    if not found:
        raise RuntimeError(
            f"Cannot resolve {MCP_BINARY!r} on this machine. "
            f"Install with `pip install 'hai-agents[mcp]'` (or `uv tool install 'hai-agents[mcp]'`), then re-run."
        )
    return os.path.realpath(found)


MCP_LEAF: dict[str, Any] = {"command": MCP_BINARY}


@dataclass(frozen=True)
class Client:
    """One MCP host: CLI hosts set `cli_add`/`cli_remove`; file hosts set `config_path` + `key_path` + `leaf`."""

    name: str
    config_path: str | None = None
    cli_add: tuple[str, ...] | None = None
    cli_remove: tuple[str, ...] | None = None
    key_path: tuple[str, ...] | None = None
    leaf: dict[str, Any] | None = None
    skills_dir: str | None = None
    home_marker: str | None = None


def _claude_desktop_config_path() -> str:
    """Per-OS Claude Desktop config path."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return str(Path(appdata) / "Claude" / "claude_desktop_config.json")
    if system == "Darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return f"{xdg}/Claude/claude_desktop_config.json"


CLIENTS: dict[str, Client] = {
    "antigravity": Client(
        name="Antigravity (Google)",
        config_path="~/.gemini/config/mcp_config.json",
        key_path=("mcpServers", SERVER_KEY),
        leaf=MCP_LEAF,
    ),
    "claude-code": Client(
        name="Claude Code",
        cli_add=("claude", "mcp", "add", "--transport", "stdio", SERVER_KEY, "--", MCP_BINARY),
        cli_remove=("claude", "mcp", "remove", SERVER_KEY),
        skills_dir=".claude/skills",
        home_marker=".claude",
    ),
    "claude-desktop": Client(
        name="Claude Desktop",
        config_path=_claude_desktop_config_path(),
        key_path=("mcpServers", SERVER_KEY),
        leaf=MCP_LEAF,
    ),
    "codex": Client(
        name="Codex (OpenAI)",
        cli_add=("codex", "mcp", "add", SERVER_KEY, "--", MCP_BINARY),
        cli_remove=("codex", "mcp", "remove", SERVER_KEY),
        skills_dir=".agents/skills",
        home_marker=".codex",
    ),
    "copilot": Client(
        name="GitHub Copilot CLI",
        config_path="~/.copilot/mcp-config.json",
        key_path=("mcpServers", SERVER_KEY),
        leaf={"type": "local", "command": MCP_BINARY, "tools": ["*"]},
    ),
    "cursor": Client(
        name="Cursor",
        config_path="~/.cursor/mcp.json",
        key_path=("mcpServers", SERVER_KEY),
        leaf={"type": "stdio", "command": MCP_BINARY},
    ),
    "opencode": Client(
        name="OpenCode",
        config_path="~/.config/opencode/opencode.json",
        key_path=("mcp", SERVER_KEY),
        leaf={"type": "local", "command": [MCP_BINARY], "enabled": True},
        skills_dir=".config/opencode/skills",
        home_marker=".config/opencode",
    ),
}


def host_present(c: Client) -> bool:
    """True if the host looks installed under $HOME."""
    home = Path.home()
    if c.home_marker and (home / c.home_marker).exists():
        return True
    return bool(c.config_path and Path(c.config_path).expanduser().parent.exists())


def host_target(c: Client) -> str:
    """Where our config lands for this host (~-path, or 'via CLI')."""
    return home_short(c.config_path) if c.config_path else "via CLI"


def _materialize_leaf(leaf: dict[str, Any]) -> dict[str, Any]:
    """Substitute the `hai-mcp` placeholder in `command`/`args` with its absolute path."""
    mcp = resolve_mcp_command()
    out: dict[str, Any] = dict(leaf)
    for k, v in list(out.items()):
        if k == "command" and isinstance(v, str) and v == MCP_BINARY:
            out[k] = mcp
        elif k in ("command", "args") and isinstance(v, list):
            out[k] = [mcp if a == MCP_BINARY else a for a in v]
    return out


def _atomic_write_text(path: Path, content: str) -> None:
    """Write+fsync to a sibling temp then `rename` over the target. Crash-safe."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not (path.exists() and path.stat().st_size > 0):
        return {}, None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"{home_short(path)}: invalid JSON ({exc})"
    if not isinstance(loaded, dict):
        return None, f"{home_short(path)}: top-level is not an object"
    return loaded, None


def _run_cli(cmd: tuple[str, ...], already_substrings: tuple[str, ...]) -> tuple[Status, str]:
    exe = shutil.which(cmd[0])
    if exe is None:
        return Status.ABSENT, f"{cmd[0]!r} not on PATH"
    resolved = [exe, *cmd[1:]]
    # Before `--` is the host's server label (stays bare); after, the binary must be absolute.
    try:
        sep = resolved.index("--")
    except ValueError:
        sep = len(resolved)
    mcp = resolve_mcp_command()
    resolved = resolved[:sep] + [mcp if a == MCP_BINARY else a for a in resolved[sep:]]
    try:
        subprocess.run(resolved, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or str(exc)).strip()
        if any(s in msg.lower() for s in already_substrings):
            return Status.SKIPPED, f"{cmd[0]} already up to date"
        return Status.FAILED, msg
    return Status.INSTALLED, f"via {cmd[0]} CLI"


def wire_mcp(c: Client) -> tuple[Status, str]:
    """Add our MCP server to host `c`: CLI add or JSON deep-merge."""
    if c.cli_add is not None:
        return _run_cli(c.cli_add, already_substrings=("already",))
    assert c.config_path is not None and c.key_path is not None and c.leaf is not None
    path = Path(c.config_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    data, error = _load_json(path)
    if data is None:
        return Status.FAILED, error or "invalid config"
    cursor: Any = data
    for k in c.key_path[:-1]:
        cursor = cursor.setdefault(k, {})
        if not isinstance(cursor, dict):
            return Status.FAILED, f"{home_short(path)}: {k!r} is not an object"
    last = c.key_path[-1]
    existing = cursor.get(last)
    leaf = _materialize_leaf(c.leaf)
    merged = {**existing, **leaf} if isinstance(existing, dict) else leaf
    if existing == merged:
        return Status.SKIPPED, home_short(path)
    cursor[last] = merged
    _atomic_write_text(path, json.dumps(data, indent=2) + "\n")
    return Status.INSTALLED, home_short(path)


def unwire_mcp(c: Client) -> tuple[Status, str]:
    """Remove our MCP server from host `c`: CLI remove or drop the JSON leaf."""
    if c.cli_remove is not None:
        return _run_cli(c.cli_remove, already_substrings=("no", "not found", "does not"))
    assert c.config_path is not None and c.key_path is not None
    path = Path(c.config_path).expanduser()
    if not path.exists():
        return Status.SKIPPED, "not configured"
    data, error = _load_json(path)
    if data is None:
        return Status.FAILED, error or "invalid config"
    cursor: Any = data
    for k in c.key_path[:-1]:
        nxt = cursor.get(k) if isinstance(cursor, dict) else None
        if not isinstance(nxt, dict):
            return Status.SKIPPED, "not configured"
        cursor = nxt
    last = c.key_path[-1]
    if not (isinstance(cursor, dict) and last in cursor):
        return Status.SKIPPED, "not configured"
    del cursor[last]
    _atomic_write_text(path, json.dumps(data, indent=2) + "\n")
    return Status.REMOVED, home_short(path)


def _skill_source() -> Path:
    return Path(str(resources.files("hai_agents_cli.host_skills").joinpath(SKILL_NAME)))


def wire_skill(c: Client) -> tuple[Status, str]:
    """Symlink the bundled SKILL.md into `c`'s skills dir (copy fallback on Windows)."""
    if c.skills_dir is None:
        return Status.SKIPPED, "no skill auto-load"
    home = Path.home()
    marker = home / (c.home_marker or PurePosixPath(c.skills_dir).parts[0])
    if not marker.exists():
        return Status.ABSENT, "host not installed"
    skills_root = home / c.skills_dir
    skills_root.mkdir(parents=True, exist_ok=True)
    link = skills_root / SKILL_NAME
    source = _skill_source()
    if link.is_symlink():
        # strict=False: a fresh-venv install can leave a symlink dangling at removed site-packages.
        if link.resolve(strict=False) == source.resolve(strict=False):
            return Status.SKIPPED, home_short(link)
        link.unlink()
    elif link.exists():
        src_md = source / "SKILL.md"
        skill_md = link / "SKILL.md"
        is_our_skill = link.is_dir() and skill_md.exists()
        if is_our_skill and src_md.exists() and skill_md.read_bytes() == src_md.read_bytes():
            return Status.SKIPPED, home_short(link)
        if not is_our_skill:
            return Status.FAILED, f"{home_short(link)} exists and is not a hai skill"
        shutil.rmtree(link)
    try:
        link.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        if os.name == "nt":
            try:
                shutil.copytree(source, link)
                return Status.INSTALLED, f"{home_short(link)} (copy; enable Developer Mode for symlinks)"
            except OSError as copy_exc:
                return Status.FAILED, f"{link}: {copy_exc}"
        return Status.FAILED, f"{link}: {exc}"
    return Status.INSTALLED, home_short(link)


def unwire_skill(c: Client) -> tuple[Status, str]:
    """Remove the symlinked/copied SKILL.md if it is ours."""
    if c.skills_dir is None:
        return Status.SKIPPED, "no skill auto-load"
    link = Path.home() / c.skills_dir / SKILL_NAME
    source = _skill_source()
    if link.is_symlink():
        if link.resolve(strict=False) == source.resolve(strict=False):
            link.unlink()
            return Status.REMOVED, home_short(link)
        return Status.SKIPPED, "not ours"
    if link.exists():
        skill_md = link / "SKILL.md"
        if link.is_dir() and skill_md.exists():
            shutil.rmtree(link)
            return Status.REMOVED, home_short(link)
        return Status.SKIPPED, "not ours"
    return Status.SKIPPED, "not configured"

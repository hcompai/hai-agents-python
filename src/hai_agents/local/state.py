"""Owner-only on-disk discovery state for locally spawned hai-agent-runtime processes.

A spawner persists the generated bearer token and the runtime pid under the SDK
cache dir so a second process can attach (token) or force-kill (pid) without any
IPC. Both files drive privileged actions, so they are 0600 from the first byte
and refuse pre-planted symlinks (port of holo_desktop launcher._write_owner_only).
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import typing

CACHE_DIR_ENV = "HAI_AGENT_LOCAL_CACHE_DIR"
DEFAULT_CACHE_DIR = pathlib.Path.home() / ".hai" / "agent-runtime"
# HoloDesktop's AGENT_API_DEFAULT_PORT: the shared well-known local runtime port.
DEFAULT_PORT = 18795

_PathInput = typing.Union[str, "os.PathLike[str]"]


def resolve_cache_dir(cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    """Explicit argument > HAI_AGENT_LOCAL_CACHE_DIR > ~/.hai/agent-runtime."""
    if cache_dir is not None:
        return pathlib.Path(cache_dir).expanduser()
    override = os.environ.get(CACHE_DIR_ENV, "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    return DEFAULT_CACHE_DIR


def state_dir(cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    return resolve_cache_dir(cache_dir) / "state"


def token_file_path(port: int, *, cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    """Where a spawner publishes its generated bearer token for other local clients."""
    return state_dir(cache_dir) / f"agent-token-{port}"


def pid_file_path(port: int, *, cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    """Where a spawner publishes the runtime pid so force_kill() works from another process."""
    return state_dir(cache_dir) / f"agent-pid-{port}"


def runtime_log_path(port: int, *, cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    """Where the runtime spawned on `port` writes its stderr."""
    return resolve_cache_dir(cache_dir) / "logs" / f"hai-agent-runtime-{port}.log"


def write_owner_only(path: pathlib.Path, content: str) -> pathlib.Path:
    """Write `content` to `path` owner-only (0600), refusing a pre-existing symlink at the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)  # owner-only state dir; no-op on Windows
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        if os.name == "posix":
            os.fchmod(fd, 0o600)  # enforce owner-only even if the file pre-existed
        fh.write(content)
    return path


def read_state_file(path: pathlib.Path) -> typing.Optional[str]:
    """The stripped file contents, or None when missing/unreadable/empty."""
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def read_pid(port: int, *, cache_dir: typing.Optional[_PathInput] = None) -> typing.Optional[int]:
    """The persisted runtime pid for `port`, or None when absent or malformed."""
    raw = read_state_file(pid_file_path(port, cache_dir=cache_dir))
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def unlink_if_content(path: pathlib.Path, content: str) -> None:
    """Remove our state file, but never one a concurrent spawner already replaced."""
    with contextlib.suppress(OSError):
        if path.read_text(encoding="utf-8").strip() == content:
            path.unlink(missing_ok=True)

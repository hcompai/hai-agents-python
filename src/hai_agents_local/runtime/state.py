"""Owner-only (0600, symlink-refusing) token and pid files that let other local processes find a spawned runtime."""

from __future__ import annotations

import contextlib
import os
import pathlib
import tempfile
import typing

CACHE_DIR_ENV = "HAI_AGENT_LOCAL_CACHE_DIR"
DEFAULT_CACHE_DIR = pathlib.Path.home() / ".hai" / "agent-runtime"
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
    """Where a spawner publishes the runtime pid for out-of-process stop tools."""
    return state_dir(cache_dir) / f"agent-pid-{port}"


def inference_file_path(port: int, *, cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    """Where a spawner records the inference its runtime serves, so attachers never borrow another's."""
    return state_dir(cache_dir) / f"agent-inference-{port}"


def runtime_log_path(port: int, *, cache_dir: typing.Optional[_PathInput] = None) -> pathlib.Path:
    """Where the runtime spawned on `port` writes its stderr."""
    return resolve_cache_dir(cache_dir) / "logs" / f"hai-agent-runtime-{port}.log"


def write_owner_only(path: pathlib.Path, content: str) -> pathlib.Path:
    """Atomically publish `content` at `path` owner-only (0600), refusing a pre-existing symlink at the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)  # owner-only state dir; no-op on Windows
    if path.is_symlink():
        raise OSError(f"refusing to replace the symlink at {path}")
    # mkstemp creates the staging file 0600 with O_EXCL, so readers only ever see complete content.
    fd, staged = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(staged, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(staged)
        raise
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
    """Remove matching state; callers must hold the startup lock against concurrent replacement."""
    with contextlib.suppress(OSError):
        if path.read_text(encoding="utf-8").strip() == content:
            path.unlink(missing_ok=True)

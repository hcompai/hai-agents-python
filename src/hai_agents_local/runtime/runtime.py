"""SDK-managed local hai-agent-runtime: install/find/start/attach/stop."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import secrets
import shutil
import subprocess
import threading
import time
import typing
from urllib.parse import urlsplit

import httpx

from hai_agents.base_client import BaseClient

from .errors import (
    BinaryIncompatibleError,
    BinaryNotFoundError,
    LocalRuntimeError,
    RuntimeUnhealthyError,
)
from .install import DOWNLOAD_SHA256_ENV, DOWNLOAD_URL_ENV, install_runtime, installed_binary, pinned_artifact
from .manifest import PINNED_RUNTIME_VERSION
from .process import (
    LOOPBACK_HOST,
    SPAWN_TIMEOUT_S,
    probe_health,
    spawn,
    terminate,
    wait_healthy,
)
from .state import (
    DEFAULT_PORT,
    pid_file_path,
    read_pid,
    read_state_file,
    resolve_cache_dir,
    runtime_log_path,
    token_file_path,
    unlink_if_content,
    write_owner_only,
)

logger = logging.getLogger(__name__)

BINARY_PATH_ENV = "HAI_AGENT_LOCAL_BINARY_PATH"
BINARY_VERSION_ENV = "HAI_AGENT_LOCAL_BINARY_VERSION"
BASE_URL_ENV = "HAI_AGENT_LOCAL_BASE_URL"
PORT_ENV = "HAI_AGENT_RUNTIME_PORT"
AUTH_TOKEN_ENV = "HAI_AGENT_RUNTIME_API_TOKEN"
CLIENT_TIMEOUT_S = 60.0

_PathInput = typing.Union[str, "os.PathLike[str]"]


def _warn_on_version_skew(version: typing.Optional[str]) -> None:
    """Warn (not fail) on a client/runtime version skew; PATH/override dev binaries stay usable."""
    if version is not None and version != PINNED_RUNTIME_VERSION:
        logger.warning(
            "hai-agent-runtime version skew: server reports %s, this SDK pins %s; "
            "wire-contract drift may cause subtle failures",
            version,
            PINNED_RUNTIME_VERSION,
        )


def _port_of(base_url: str) -> int:
    return urlsplit(base_url).port or DEFAULT_PORT


class LocalRuntime:
    """A reachable local agent runtime: where it is, how to authenticate, and (if ours) the process."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        pid: typing.Optional[int],
        version: typing.Optional[str],
        log_path: typing.Optional[pathlib.Path],
        owned: bool,
        cache_dir: pathlib.Path,
        port: int,
        proc: typing.Optional[subprocess.Popen] = None,
        token_file: typing.Optional[pathlib.Path] = None,
        pid_file: typing.Optional[pathlib.Path] = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.pid = pid
        self.version = version
        self.log_path = log_path
        self.owned = owned
        self._cache_dir = cache_dir
        self._port = port
        self._proc = proc
        # Set only on the spawner that published generated state; attachers never own the files.
        self._token_file = token_file
        self._pid_file = pid_file

    @classmethod
    def ensure_started(
        cls,
        *,
        required_recipe: typing.Optional[str] = None,
        command: typing.Optional[typing.Sequence[str]] = None,
        binary_path: typing.Optional[_PathInput] = None,
        version: typing.Optional[str] = None,
        cache_dir: typing.Optional[_PathInput] = None,
        port: typing.Optional[int] = None,
        spawn_env: typing.Optional[typing.Dict[str, str]] = None,
        inherit_env: bool = True,
        download: bool = True,
        timeout_s: float = SPAWN_TIMEOUT_S,
        _cancel_event: typing.Optional[threading.Event] = None,
    ) -> "LocalRuntime":
        """Return a reachable LocalRuntime, attaching to an existing one or spawning the binary."""
        resolved_cache = resolve_cache_dir(cache_dir)
        base_override = os.environ.get(BASE_URL_ENV, "").strip()
        if base_override:
            attached = cls._attach(base_url=base_override.rstrip("/"), cache_dir=resolved_cache)
            if attached is None:
                raise RuntimeUnhealthyError(
                    f"{BASE_URL_ENV} is set to {base_override} but /health is not answering there"
                )
            attached.require_recipe(required_recipe)
            return attached

        resolved_port = port if port is not None else int(os.environ.get(PORT_ENV, "").strip() or DEFAULT_PORT)
        base_url = f"http://{LOOPBACK_HOST}:{resolved_port}"
        attached = cls._attach(base_url=base_url, cache_dir=resolved_cache)
        if attached is not None:
            attached.require_recipe(required_recipe)
            return attached

        if command is not None and (not command or binary_path is not None):
            raise ValueError("command must be nonempty and cannot be combined with binary_path")
        # Downloads are atomically installed and can outlast the process health budget.
        # Keep them outside the port lock; recheck attachment before spawning.
        cmd = (
            list(command)
            if command is not None
            else cls._resolve_command(
                binary_path=binary_path, version=version, cache_dir=resolved_cache, download=download
            )
        )
        with _startup_lock(resolved_cache, resolved_port, timeout_s):
            attached = cls._attach(base_url=base_url, cache_dir=resolved_cache)
            if attached is not None:
                attached.require_recipe(required_recipe)
                return attached

            if _cancel_event is not None and _cancel_event.is_set():
                raise RuntimeUnhealthyError("runtime startup cancelled")
            explicit_token = (
                (spawn_env or {}).get(AUTH_TOKEN_ENV, os.environ.get(AUTH_TOKEN_ENV, "") if inherit_env else "").strip()
            )
            token = explicit_token or secrets.token_urlsafe(32)
            # Publish the token before the health wait so a client racing our probe can authenticate.
            token_file = (
                None
                if explicit_token
                else write_owner_only(token_file_path(resolved_port, cache_dir=resolved_cache), token)
            )
            log_path = runtime_log_path(resolved_port, cache_dir=resolved_cache)
            proc = None
            try:
                proc = spawn(
                    cmd,
                    env=cls._child_env(port=resolved_port, token=token, spawn_env=spawn_env, inherit_env=inherit_env),
                    log_path=log_path,
                )
                payload = wait_healthy(
                    base_url, proc, timeout_s=timeout_s, log_path=log_path, cancel_event=_cancel_event
                )
                response = httpx.get(
                    f"{base_url}/api/v2/sessions",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"size": 1},
                    timeout=2.0,
                    follow_redirects=False,
                    trust_env=False,
                )
                if required_recipe is not None and payload.get("recipe") != required_recipe:
                    raise BinaryIncompatibleError(
                        f"runtime must support recipe {required_recipe!r}; use a compatible source command or binary"
                    )
                if response.status_code != 200 or proc.poll() is not None:
                    raise RuntimeUnhealthyError("spawned runtime failed authenticated readiness probe")
                pid_file = write_owner_only(pid_file_path(resolved_port, cache_dir=resolved_cache), str(proc.pid))
            except BaseException:
                # Covers KeyboardInterrupt mid-spawn: never leak the child or its token file.
                if proc is not None:
                    terminate(proc)
                if token_file is not None:
                    unlink_if_content(token_file, token)
                raise
            reported = payload.get("version")
            reported_version = reported if isinstance(reported, str) else None
            _warn_on_version_skew(reported_version)
            return cls(
                base_url=base_url,
                api_key=token,
                pid=proc.pid,
                version=reported_version,
                log_path=log_path,
                owned=True,
                cache_dir=resolved_cache,
                port=resolved_port,
                proc=proc,
                token_file=token_file,
                pid_file=pid_file,
            )

    @classmethod
    async def ensure_started_async(cls, **options: typing.Any) -> "LocalRuntime":
        """Start off the event loop; cancellation cleans up an owned child before returning."""
        cancelled = threading.Event()
        startup = asyncio.create_task(asyncio.to_thread(cls.ensure_started, _cancel_event=cancelled, **options))
        try:
            return await asyncio.shield(startup)
        except asyncio.CancelledError:
            cancelled.set()
            # The worker may have finished between shield cancellation and setting the event.
            with contextlib.suppress(Exception):
                runtime = await startup
                if runtime.owned:
                    await asyncio.to_thread(runtime.shutdown)
            raise

    def require_recipe(self, recipe: typing.Optional[str]) -> None:
        """Fail closed when an old binary or a differently configured daemon answers."""
        if recipe is None:
            return
        payload = probe_health(self.base_url)
        if payload is None or payload.get("recipe") != recipe:
            raise BinaryIncompatibleError(
                f"runtime must support recipe {recipe!r}; use a compatible source command or binary"
            )

    @classmethod
    def attach(
        cls, *, port: typing.Optional[int] = None, cache_dir: typing.Optional[_PathInput] = None
    ) -> typing.Optional["LocalRuntime"]:
        """A LocalRuntime for an already-running local runtime, or None when nothing answers /health."""
        resolved_cache = resolve_cache_dir(cache_dir)
        base_override = os.environ.get(BASE_URL_ENV, "").strip()
        if base_override:
            return cls._attach(base_url=base_override.rstrip("/"), cache_dir=resolved_cache)
        resolved_port = port if port is not None else int(os.environ.get(PORT_ENV, "").strip() or DEFAULT_PORT)
        return cls._attach(base_url=f"http://{LOOPBACK_HOST}:{resolved_port}", cache_dir=resolved_cache)

    @classmethod
    def _attach(cls, *, base_url: str, cache_dir: pathlib.Path) -> typing.Optional["LocalRuntime"]:
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username:
            raise LocalRuntimeError("local runtime attachment requires a loopback HTTP URL")
        port = _port_of(base_url)
        payload = probe_health(base_url)
        if payload is None:
            return None
        token = os.environ.get(AUTH_TOKEN_ENV, "").strip() or read_state_file(
            token_file_path(port, cache_dir=cache_dir)
        )
        if not token:
            raise LocalRuntimeError(
                f"an agent runtime is answering at {base_url} but no credentials were found: "
                f"{AUTH_TOKEN_ENV} is not set and {token_file_path(port, cache_dir=cache_dir)} does not exist, "
                "so this client cannot authenticate. Export the token or stop that runtime."
            )
        try:
            response = httpx.get(
                f"{base_url}/api/v2/sessions",
                headers={"Authorization": f"Bearer {token}"},
                params={"size": 1},
                timeout=2.0,
                follow_redirects=False,
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            raise LocalRuntimeError("runtime attachment failed authenticated session probe") from exc
        if response.status_code != 200:
            raise LocalRuntimeError("runtime attachment failed authenticated session probe")
        reported = payload.get("version")
        reported_version = reported if isinstance(reported, str) else None
        _warn_on_version_skew(reported_version)
        log_path = runtime_log_path(port, cache_dir=cache_dir)
        return cls(
            base_url=base_url,
            api_key=token,
            pid=read_pid(port, cache_dir=cache_dir),
            version=reported_version,
            log_path=log_path if log_path.exists() else None,
            owned=False,
            cache_dir=cache_dir,
            port=port,
        )

    @staticmethod
    def _child_env(
        *,
        port: int,
        token: str,
        spawn_env: typing.Optional[typing.Dict[str, str]],
        inherit_env: bool,
    ) -> typing.Dict[str, str]:
        """Child env: inherited-plus-overlay by default, caller-verbatim with inherit_env=False.

        Inheriting os.environ passes the model-gateway HAI_API_KEY / HAI_BASE_URL through to the
        binary (without them local sessions cannot run inference) and forwards caller flags such as
        HAI_AGENT_RUNTIME_MODEL/FAKE/FAST/RUNS_DIR. inherit_env=False takes spawn_env as the
        complete base environment instead — for callers that must *remove* inherited keys, which an
        overlay cannot express (e.g. stripping HAI_API_KEY for self-hosted base URLs). The
        generated local bearer and the cloud HAI_API_KEY are different credentials: the token below
        is the only local bearer, and the cloud key is never used to authenticate against the local
        runtime. Port and token are set last in both modes so caller input never clobbers them.
        """
        env = {**os.environ, **(spawn_env or {})} if inherit_env else dict(spawn_env or {})
        env[PORT_ENV] = str(port)
        env[AUTH_TOKEN_ENV] = token
        return env

    @staticmethod
    def _resolve_command(
        *,
        binary_path: typing.Optional[_PathInput],
        version: typing.Optional[str],
        cache_dir: pathlib.Path,
        download: bool,
    ) -> typing.List[str]:
        """Explicit path > HAI_AGENT_LOCAL_BINARY_PATH > PATH > managed install > verified download."""
        explicit = str(binary_path) if binary_path is not None else os.environ.get(BINARY_PATH_ENV, "").strip()
        if explicit:
            candidate = pathlib.Path(explicit).expanduser()
            if not candidate.is_file():
                raise BinaryNotFoundError(f"binary_path / {BINARY_PATH_ENV} points at a missing file: {candidate}")
            return [str(candidate)]
        found = shutil.which("hai-agent-runtime")
        if found:
            logger.info("resolved hai-agent-runtime from PATH: %s", found)
            return [found]
        pinned = version or os.environ.get(BINARY_VERSION_ENV, "").strip() or PINNED_RUNTIME_VERSION
        managed = installed_binary(pinned, cache_dir=cache_dir)
        if managed is not None:
            logger.info("resolved hai-agent-runtime from managed install v%s: %s", pinned, managed)
            return [str(managed)]
        if not download:
            raise BinaryNotFoundError(
                "hai-agent-runtime not found: not on PATH, no managed install under "
                f"{cache_dir / 'bin'}, and download=False. Pass binary_path=, set {BINARY_PATH_ENV}, "
                "or allow download=True."
            )
        if pinned != PINNED_RUNTIME_VERSION and not os.environ.get(DOWNLOAD_URL_ENV, "").strip():
            raise BinaryIncompatibleError(
                f"cannot download hai-agent-runtime {pinned}: this SDK pins sha256 digests for "
                f"{PINNED_RUNTIME_VERSION} only. Install {pinned} yourself, or set "
                f"{DOWNLOAD_URL_ENV} + {DOWNLOAD_SHA256_ENV} to a trusted build."
            )
        installed = install_runtime(pinned_artifact(), version=pinned, cache_dir=cache_dir)
        logger.info("resolved hai-agent-runtime from fresh download v%s: %s", pinned, installed)
        return [str(installed)]

    def http_client(self, timeout: typing.Optional[float] = None) -> httpx.Client:
        """An HTTP client for this runtime's API."""
        return httpx.Client(
            timeout=CLIENT_TIMEOUT_S if timeout is None else timeout, follow_redirects=True, trust_env=False
        )

    def async_http_client(self, timeout: typing.Optional[float] = None) -> httpx.AsyncClient:
        """An asynchronous HTTP client for this runtime's API."""
        return httpx.AsyncClient(
            timeout=CLIENT_TIMEOUT_S if timeout is None else timeout, follow_redirects=True, trust_env=False
        )

    def health(self) -> typing.Dict[str, typing.Any]:
        """The /health JSON body; raises RuntimeUnhealthyError when the runtime is not answering."""
        payload = probe_health(self.base_url)
        if payload is None:
            raise RuntimeUnhealthyError(f"hai-agent-runtime at {self.base_url} is not answering /health")
        return payload

    def shutdown(self) -> None:
        """Gracefully stop the runtime this LocalRuntime spawned (SIGTERM group, grace, SIGKILL group)."""
        if not self.owned or self._proc is None:
            raise LocalRuntimeError("shutdown() only stops runtimes this LocalRuntime spawned")
        terminate(self._proc)
        self._cleanup_state_files()

    # Statuses that mean the runtime still holds live session state a shutdown would destroy.
    # ("idle" sessions await user input but keep runtime state.)
    ACTIVE_SESSION_STATUSES: typing.ClassVar[typing.Tuple[str, ...]] = (
        "pending",
        "running",
        "paused",
        "idle",
        "awaiting_tool_results",
    )

    def shutdown_if_idle(self) -> bool:
        """Stop the owned runtime only when it hosts no active sessions; True when it was stopped."""
        with self.http_client() as http:
            client = BaseClient(base_url=self.base_url, api_key=self.api_key, httpx_client=http)
            page = client.sessions.list_sessions(status=list(self.ACTIVE_SESSION_STATUSES), size=1)
            if page.items:
                return False
        self.shutdown()
        return True

    def force_kill(self) -> None:
        """Stop only the process this manager spawned; never trust a saved PID to claim ownership."""
        if not self.owned or self._proc is None:
            raise LocalRuntimeError("cannot force-kill a borrowed runtime from a persisted PID")
        terminate(self._proc)
        self._cleanup_state_files()

    def _cleanup_state_files(self) -> None:
        # Serialize compare-and-unlink with publication of a replacement runtime's state.
        with _startup_lock(self._cache_dir, self._port, SPAWN_TIMEOUT_S):
            if self._token_file is not None:
                unlink_if_content(self._token_file, self.api_key)
                self._token_file = None
            if self._pid_file is not None:
                unlink_if_content(self._pid_file, str(self.pid))
                self._pid_file = None


@contextlib.contextmanager
def _startup_lock(cache_dir: pathlib.Path, port: int, timeout_s: float):
    path = cache_dir / "state" / f"startup-{port}.lock"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+b") as handle:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise LocalRuntimeError("timed out waiting for local runtime startup lock")
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

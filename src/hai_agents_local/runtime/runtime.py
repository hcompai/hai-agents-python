"""SDK-managed local hai-agent-runtime: install/find/start/attach/stop."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
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

from . import identity
from .errors import (
    BinaryIncompatibleError,
    BinaryNotFoundError,
    LocalRuntimeError,
    RuntimeUnhealthyError,
)
from .inference import HOSTED, served_inference
from .install import DOWNLOAD_SHA256_ENV, DOWNLOAD_URL_ENV, install_runtime, installed_binary, pinned_artifact
from .manifest import PINNED_RUNTIME_VERSION
from .process import (
    KILL_WAIT_S,
    LOOPBACK_HOST,
    SPAWN_TIMEOUT_S,
    TERM_GRACE_S,
    probe_health,
    responds,
    spawn,
    terminate,
    wait_healthy,
)
from .state import (
    DEFAULT_PORT,
    inference_file_path,
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
IDLE_PROBE_PAGE_SIZE = 50
INFERENCE_PORTS = 1000
# Beyond the holder's health budget: its authenticated probe, then a failed child's graceful stop.
STARTUP_LOCK_GRACE_S = TERM_GRACE_S + KILL_WAIT_S + 5.0

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


def _inference_record(served: str, pid: int) -> str:
    """The pid keeps each runtime's record unique, so a stopping runtime never unlinks its successor's."""
    return f"{served}\n{pid}"


def _served_from_record(record: typing.Optional[str]) -> typing.Optional[str]:
    return record.splitlines()[0] if record else None


def default_port(served: str) -> int:
    """Hosted inference on ``DEFAULT_PORT``; any other inference on its own stable port, so both run side by side."""
    if served == HOSTED:
        return DEFAULT_PORT
    return DEFAULT_PORT + 1 + int(hashlib.sha256(served.encode()).hexdigest(), 16) % INFERENCE_PORTS


def _authenticated_probe(base_url: str, token: str) -> int:
    """Status of a proven, bearer-authenticated session listing; call only after /health proved the server."""
    with identity.http_client(token, timeout=2.0) as client:
        response = client.get(
            f"{base_url}/api/v2/sessions",
            headers={"Authorization": f"Bearer {token}"},
            params={"size": 1},
            follow_redirects=False,
        )
    return response.status_code


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
        serves: typing.Optional[str] = None,
        inference_file: typing.Optional[pathlib.Path] = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.pid = pid
        self.version = version
        self.log_path = log_path
        self.owned = owned
        # None for a runtime started before spawners recorded their inference.
        self.serves = serves
        self._cache_dir = cache_dir
        self._port = port
        self._proc = proc
        # Set only on the spawner that published generated state; attachers never own the files.
        self._token_file = token_file
        self._pid_file = pid_file
        self._inference_file = inference_file

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
        served = served_inference(cls._child_env(port=0, token="", spawn_env=spawn_env, inherit_env=inherit_env))
        base_override = os.environ.get(BASE_URL_ENV, "").strip()
        if base_override:
            attached = cls._attach(base_url=base_override.rstrip("/"), cache_dir=resolved_cache)
            if attached is None:
                raise RuntimeUnhealthyError(
                    f"{BASE_URL_ENV} is set to {base_override} but /health is not answering there"
                )
            return attached._verified(required_recipe, served)

        resolved_port = port if port is not None else int(os.environ.get(PORT_ENV, "").strip() or default_port(served))
        base_url = f"http://{LOOPBACK_HOST}:{resolved_port}"
        lock_wait_s = timeout_s + STARTUP_LOCK_GRACE_S
        try:
            attached = cls._attach(base_url=base_url, cache_dir=resolved_cache)
        except LocalRuntimeError:
            # A concurrent spawner publishes its token only after its child is proven; decide once it has.
            with _startup_lock(resolved_cache, resolved_port, lock_wait_s):
                attached = cls._attach(base_url=base_url, cache_dir=resolved_cache)
        if attached is not None:
            return attached._verified(required_recipe, served)

        if command is not None and (not command or binary_path is not None):
            raise ValueError("command must be nonempty and cannot be combined with binary_path")
        # Downloads can outlast the lock budget: resolve outside it, then recheck attachment under it.
        cmd = (
            list(command)
            if command is not None
            else cls._resolve_command(
                binary_path=binary_path, version=version, cache_dir=resolved_cache, download=download
            )
        )
        with _startup_lock(resolved_cache, resolved_port, lock_wait_s):
            attached = cls._attach(base_url=base_url, cache_dir=resolved_cache)
            if attached is not None:
                return attached._verified(required_recipe, served)

            if _cancel_event is not None and _cancel_event.is_set():
                raise RuntimeUnhealthyError("runtime startup cancelled")
            explicit_token = (
                (spawn_env or {}).get(AUTH_TOKEN_ENV, os.environ.get(AUTH_TOKEN_ENV, "") if inherit_env else "").strip()
            )
            token = explicit_token or secrets.token_urlsafe(32)
            log_path = runtime_log_path(resolved_port, cache_dir=resolved_cache)
            proc = None
            token_file = None
            inference_file = None
            try:
                proc = spawn(
                    cmd,
                    env=cls._child_env(port=resolved_port, token=token, spawn_env=spawn_env, inherit_env=inherit_env),
                    log_path=log_path,
                )
                payload = wait_healthy(
                    base_url, proc, token=token, timeout_s=timeout_s, log_path=log_path, cancel_event=_cancel_event
                )
                status = _authenticated_probe(base_url, token)
                if required_recipe is not None and payload.get("recipe") != required_recipe:
                    raise BinaryIncompatibleError(
                        f"runtime must support recipe {required_recipe!r}; use a compatible source command or binary"
                    )
                if status != 200 or proc.poll() is not None:
                    raise RuntimeUnhealthyError("spawned runtime failed authenticated readiness probe")
                # Published only once the child proved it owns the port, so another runtime's file is never replaced.
                if not explicit_token:
                    token_file = write_owner_only(token_file_path(resolved_port, cache_dir=resolved_cache), token)
                inference_file = write_owner_only(
                    inference_file_path(resolved_port, cache_dir=resolved_cache), _inference_record(served, proc.pid)
                )
                pid_file = write_owner_only(pid_file_path(resolved_port, cache_dir=resolved_cache), str(proc.pid))
            except BaseException:
                # Covers KeyboardInterrupt mid-spawn: never leak the child or its state files.
                if proc is not None:
                    terminate(proc)
                if token_file is not None:
                    unlink_if_content(token_file, token)
                if inference_file is not None and proc is not None:
                    unlink_if_content(inference_file, _inference_record(served, proc.pid))
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
                serves=served,
                inference_file=inference_file,
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
        payload = probe_health(self.base_url, self.api_key)
        if payload is None or payload.get("recipe") != recipe:
            raise BinaryIncompatibleError(
                f"runtime must support recipe {recipe!r}; use a compatible source command or binary"
            )

    def _verified(self, recipe: typing.Optional[str], served: str) -> "LocalRuntime":
        """This runtime, once it supports ``recipe`` and was not started for another inference than ``served``."""
        self.require_recipe(recipe)
        if self.serves is not None and self.serves != served:
            raise LocalRuntimeError(
                f"the runtime at {self.base_url} infers against {self.serves}, not {served}; "
                f"set {PORT_ENV} to run another one"
            )
        return self

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
        token = os.environ.get(AUTH_TOKEN_ENV, "").strip() or read_state_file(
            token_file_path(port, cache_dir=cache_dir)
        )
        if not token:
            if not responds(base_url):
                return None
            raise LocalRuntimeError(
                f"an agent runtime is answering at {base_url} but no credentials were found: "
                f"{AUTH_TOKEN_ENV} is not set and {token_file_path(port, cache_dir=cache_dir)} does not exist, "
                "so this client cannot authenticate. Export the token or stop that runtime."
            )
        payload = probe_health(base_url, token)
        if payload is None:
            return None
        try:
            status = _authenticated_probe(base_url, token)
        except httpx.HTTPError as exc:
            raise LocalRuntimeError("runtime attachment failed authenticated session probe") from exc
        if status != 200:
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
            serves=_served_from_record(read_state_file(inference_file_path(port, cache_dir=cache_dir))),
        )

    @staticmethod
    def _child_env(
        *,
        port: int,
        token: str,
        spawn_env: typing.Optional[typing.Dict[str, str]],
        inherit_env: bool,
    ) -> typing.Dict[str, str]:
        """os.environ plus spawn_env, or spawn_env verbatim to drop inherited keys; port and token always win."""
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
        """An HTTP client for this runtime's API that rejects responses this runtime did not prove."""
        return identity.http_client(
            self.api_key, timeout=CLIENT_TIMEOUT_S if timeout is None else timeout, follow_redirects=True
        )

    def async_http_client(self, timeout: typing.Optional[float] = None) -> httpx.AsyncClient:
        """``http_client`` for asyncio callers."""
        return identity.async_http_client(
            self.api_key, timeout=CLIENT_TIMEOUT_S if timeout is None else timeout, follow_redirects=True
        )

    @property
    def child_alive(self) -> bool:
        """True while the process this LocalRuntime spawned is still running."""
        return self._proc is not None and self._proc.poll() is None

    def shutdown(self) -> None:
        """Gracefully stop the runtime this LocalRuntime spawned (SIGTERM group, grace, SIGKILL group)."""
        if not self.owned or self._proc is None:
            raise LocalRuntimeError("shutdown() only stops runtimes this LocalRuntime spawned")
        terminate(self._proc)
        self._cleanup_state_files()

    # Statuses whose runtime state a shutdown would destroy ("idle" awaits user input but keeps state).
    ACTIVE_SESSION_STATUSES: typing.ClassVar[typing.Tuple[str, ...]] = (
        "queued",
        "pending",
        "running",
        "paused",
        "idle",
        "awaiting_tool_results",
    )

    def shutdown_if_idle(self, ignore: typing.Collection[str] = ()) -> bool:
        """Stop the owned runtime unless it hosts an active session outside ``ignore``; True when it was stopped."""
        # Only spawns and locked attaches are serialized; an unlocked attacher can still race the listing.
        with _startup_lock(self._cache_dir, self._port, SPAWN_TIMEOUT_S + STARTUP_LOCK_GRACE_S):
            try:
                if self._hosts_active_session(ignore):
                    return False
            except Exception:
                logger.warning("idle probe failed on %s; stopping the owned runtime", self.base_url, exc_info=True)
            self.shutdown()
        return True

    def _hosts_active_session(self, ignore: typing.Collection[str]) -> bool:
        with self.http_client() as http:
            sessions = BaseClient(base_url=self.base_url, api_key=self.api_key, httpx_client=http).sessions
            page, seen = 1, 0
            while True:
                listed = sessions.list_sessions(
                    status=list(self.ACTIVE_SESSION_STATUSES), page=page, size=IDLE_PROBE_PAGE_SIZE
                )
                if any(item.id not in ignore for item in listed.items):
                    return True
                seen += len(listed.items)
                if not listed.items or seen >= listed.total:
                    return False
                page += 1

    def _cleanup_state_files(self) -> None:
        # Serialize compare-and-unlink with publication of a replacement runtime's state.
        with _startup_lock(self._cache_dir, self._port, SPAWN_TIMEOUT_S + STARTUP_LOCK_GRACE_S):
            if self._token_file is not None:
                unlink_if_content(self._token_file, self.api_key)
                self._token_file = None
            if self._pid_file is not None:
                unlink_if_content(self._pid_file, str(self.pid))
                self._pid_file = None
            if self._inference_file is not None and self.serves is not None and self.pid is not None:
                unlink_if_content(self._inference_file, _inference_record(self.serves, self.pid))
                self._inference_file = None


def locate_runtime() -> typing.Optional[str]:
    """The binary ``Client.local`` would start, without downloading; None when it would download first."""
    try:
        command = LocalRuntime._resolve_command(
            binary_path=None, version=None, cache_dir=resolve_cache_dir(), download=False
        )
    except BinaryNotFoundError:
        return None
    return command[0]


_held_startup_locks = threading.local()


@contextlib.contextmanager
def _startup_lock(cache_dir: pathlib.Path, port: int, timeout_s: float):
    path = cache_dir / "state" / f"startup-{port}.lock"
    # Reentrant per thread: a second open file description would block on this thread's own flock.
    held: typing.Set[pathlib.Path] = _held_startup_locks.__dict__.setdefault("paths", set())
    if path in held:
        yield
        return
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
        held.add(path)
        try:
            yield
        finally:
            held.discard(path)
            if os.name == "posix":
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

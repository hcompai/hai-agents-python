"""SDK-managed local hai-agent-runtime: install/find/start/attach/stop."""

from __future__ import annotations

import logging
import os
import pathlib
import secrets
import shutil
import subprocess
import typing
from urllib.parse import urlsplit

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
    kill_process_group,
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
        binary_path: typing.Optional[_PathInput] = None,
        version: typing.Optional[str] = None,
        cache_dir: typing.Optional[_PathInput] = None,
        port: typing.Optional[int] = None,
        spawn_env: typing.Optional[typing.Dict[str, str]] = None,
        inherit_env: bool = True,
        download: bool = True,
        timeout_s: float = SPAWN_TIMEOUT_S,
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
            return attached

        resolved_port = port if port is not None else int(os.environ.get(PORT_ENV, "").strip() or DEFAULT_PORT)
        base_url = f"http://{LOOPBACK_HOST}:{resolved_port}"
        attached = cls._attach(base_url=base_url, cache_dir=resolved_cache)
        if attached is not None:
            return attached

        cmd = cls._resolve_command(
            binary_path=binary_path, version=version, cache_dir=resolved_cache, download=download
        )
        token = secrets.token_urlsafe(32)
        # Publish the token before the health wait so a client racing our probe can authenticate.
        token_file = write_owner_only(token_file_path(resolved_port, cache_dir=resolved_cache), token)
        log_path = runtime_log_path(resolved_port, cache_dir=resolved_cache)
        proc = spawn(
            cmd,
            env=cls._child_env(port=resolved_port, token=token, spawn_env=spawn_env, inherit_env=inherit_env),
            log_path=log_path,
        )
        try:
            payload = wait_healthy(base_url, proc, timeout_s=timeout_s, log_path=log_path)
        except BaseException:
            # Covers KeyboardInterrupt mid-spawn: never leak the child or its token file.
            terminate(proc)
            unlink_if_content(token_file, token)
            raise
        pid_file = write_owner_only(pid_file_path(resolved_port, cache_dir=resolved_cache), str(proc.pid))
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
        overlay cannot express (HoloDesktop strips HAI_API_KEY for self-hosted base URLs). The
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

    def health(self) -> typing.Dict[str, typing.Any]:
        """The /health JSON body; raises RuntimeUnhealthyError when the runtime is not answering."""
        payload = probe_health(self.base_url)
        if payload is None:
            raise RuntimeUnhealthyError(f"hai-agent-runtime at {self.base_url} is not answering /health")
        return payload

    def shutdown(self) -> None:
        """Gracefully stop the runtime this LocalRuntime spawned (SIGTERM group, grace, SIGKILL group)."""
        if not self.owned or self._proc is None:
            raise LocalRuntimeError(
                "shutdown() only stops runtimes this LocalRuntime spawned; "
                "use force_kill() to stop a runtime you attached to"
            )
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
        from ..client import Client  # runtime-time import: client.py imports this module lazily too

        client = Client(base_url=self.base_url, api_key=self.api_key)
        page = client.sessions.list_sessions(status=list(self.ACTIVE_SESSION_STATUSES), size=1)
        if page.items:
            return False
        self.shutdown()
        return True

    def force_kill(self) -> None:
        """SIGKILL the runtime's process group via the persisted pid; works from any process.

        This is what backs ``holo stop --force``: it needs only the pid file, not the
        Popen handle, so an attached manager (or a brand-new process) can use it.
        """
        pid = self.pid if self.pid is not None else read_pid(self._port, cache_dir=self._cache_dir)
        if pid is None:
            raise LocalRuntimeError(f"no pid recorded for the runtime on port {self._port}; nothing to kill")
        if not kill_process_group(pid):
            logger.info("hai-agent-runtime pid %d was already gone", pid)
        pid_file_path(self._port, cache_dir=self._cache_dir).unlink(missing_ok=True)
        unlink_if_content(token_file_path(self._port, cache_dir=self._cache_dir), self.api_key)

    def _cleanup_state_files(self) -> None:
        if self._token_file is not None:
            unlink_if_content(self._token_file, self.api_key)
            self._token_file = None
        if self._pid_file is not None:
            self._pid_file.unlink(missing_ok=True)
            self._pid_file = None

"""The runtime behind ``Client.local``: a caller-provided one, or a shared-recipe runtime started for the client."""

from __future__ import annotations

import asyncio
import threading
import typing

import httpx

from hai_agents.client import API_KEY_VAR, default_api_key

from . import identity
from .errors import LocalRuntimeError
from .inference import Inference
from .process import probe_health
from .runtime import CLIENT_TIMEOUT_S, LocalRuntime

SHARED_RECIPE = "shared"
RECIPE_ENV = "HAI_AGENT_RUNTIME_RECIPE"

# Runtimes this process spawned, by base URL: every client of this process shares their ownership,
# so the last one to close stops the child instead of leaving it to the parent watchdog.
_spawned_here: typing.Dict[str, LocalRuntime] = {}
_spawned_lock = threading.Lock()


def acquire_runtime(
    runtime: typing.Optional[LocalRuntime],
    *,
    inference: typing.Optional[Inference],
    local_options: typing.Optional[typing.Dict[str, typing.Any]],
) -> typing.Tuple[LocalRuntime, bool]:
    """The runtime a local client talks to, and whether this process owns (and so stops) it."""
    if runtime is not None:
        _require_unconfigured(inference, local_options)
        runtime.require_recipe(SHARED_RECIPE)
        return runtime, False
    started = LocalRuntime.ensure_started(**_launch_options(inference, local_options))
    return _claim(started, inference)


async def acquire_runtime_async(
    runtime: typing.Optional[LocalRuntime],
    *,
    inference: typing.Optional[Inference],
    local_options: typing.Optional[typing.Dict[str, typing.Any]],
) -> typing.Tuple[LocalRuntime, bool]:
    """``acquire_runtime`` off the event loop; cancellation stops a runtime started for the client."""
    if runtime is not None:
        _require_unconfigured(inference, local_options)
        await asyncio.to_thread(runtime.require_recipe, SHARED_RECIPE)
        return runtime, False
    started = await LocalRuntime.ensure_started_async(**_launch_options(inference, local_options))
    return _claim(started, inference)


class RuntimeHold:
    """A client's runtime, and how to get it back once the process that spawned it has exited.

    A runtime lives as long as its spawner (parent watchdog). A client that merely attached to it
    is left talking to a closed port, so before new work it re-acquires: another runtime at the
    same place, possibly under a new token, which the HTTP layer picks up through ``api_key``.
    """

    def __init__(
        self,
        runtime: LocalRuntime,
        owned: bool,
        *,
        launch: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> None:
        self.runtime = runtime
        self.owned = owned
        self._launch = launch

    @classmethod
    def acquire(
        cls,
        runtime: typing.Optional[LocalRuntime],
        *,
        inference: typing.Optional[Inference],
        local_options: typing.Optional[typing.Dict[str, typing.Any]],
    ) -> "RuntimeHold":
        acquired, owned = acquire_runtime(runtime, inference=inference, local_options=local_options)
        return cls(acquired, owned, launch=_relaunch(runtime, inference, local_options))

    @classmethod
    async def acquire_async(
        cls,
        runtime: typing.Optional[LocalRuntime],
        *,
        inference: typing.Optional[Inference],
        local_options: typing.Optional[typing.Dict[str, typing.Any]],
    ) -> "RuntimeHold":
        acquired, owned = await acquire_runtime_async(runtime, inference=inference, local_options=local_options)
        return cls(acquired, owned, launch=_relaunch(runtime, inference, local_options))

    def api_key(self) -> str:
        return self.runtime.api_key

    def http_client(self, timeout: typing.Optional[float] = None) -> httpx.Client:
        return identity.http_client(
            self.api_key, timeout=CLIENT_TIMEOUT_S if timeout is None else timeout, follow_redirects=True
        )

    def async_http_client(self, timeout: typing.Optional[float] = None) -> httpx.AsyncClient:
        return identity.async_http_client(
            self.api_key, timeout=CLIENT_TIMEOUT_S if timeout is None else timeout, follow_redirects=True
        )

    def lost(self) -> bool:
        """The runtime this client attached to is gone: nothing answers, or a runtime under another token took its port."""
        if self._launch is None or self.owned:
            return False
        try:
            return probe_health(self.runtime.base_url, self.runtime.api_key) is None
        except LocalRuntimeError:
            return True

    def reacquire(self) -> bool:
        """Replace a lost runtime; True when the client now talks to another one."""
        if not self.lost():
            return False
        self._replace(*acquire_runtime(None, **typing.cast(typing.Dict[str, typing.Any], self._launch)))
        return True

    async def reacquire_async(self) -> bool:
        if not await asyncio.to_thread(self.lost):
            return False
        self._replace(*await acquire_runtime_async(None, **typing.cast(typing.Dict[str, typing.Any], self._launch)))
        return True

    def _replace(self, runtime: LocalRuntime, owned: bool) -> None:
        if runtime.base_url != self.runtime.base_url:
            raise LocalRuntimeError(
                f"the replacement runtime listens at {runtime.base_url}, not {self.runtime.base_url}"
            )
        self.runtime, self.owned = runtime, owned


def _relaunch(
    runtime: typing.Optional[LocalRuntime],
    inference: typing.Optional[Inference],
    local_options: typing.Optional[typing.Dict[str, typing.Any]],
) -> typing.Optional[typing.Dict[str, typing.Any]]:
    """How to acquire again; None for a caller-provided runtime, whose lifetime is the caller's business."""
    if runtime is not None:
        return None
    return {"inference": inference, "local_options": local_options}


def _require_unconfigured(
    inference: typing.Optional[Inference], local_options: typing.Optional[typing.Dict[str, typing.Any]]
) -> None:
    if inference is not None or local_options is not None:
        raise ValueError("an attached runtime owns its inference and launch configuration")


def _launch_options(
    inference: typing.Optional[Inference], local_options: typing.Optional[typing.Dict[str, typing.Any]]
) -> typing.Dict[str, typing.Any]:
    options = dict(local_options or {})
    options["required_recipe"] = SHARED_RECIPE
    options["spawn_env"] = {RECIPE_ENV: SHARED_RECIPE, **options.get("spawn_env", {})}
    api_key = default_api_key()
    if api_key is not None:
        options["spawn_env"].setdefault(API_KEY_VAR, api_key)
    if inference is not None:
        options["spawn_env"] = inference.runtime_env(options["spawn_env"])
        options["inherit_env"] = False
    return options


def _claim(runtime: LocalRuntime, inference: typing.Optional[Inference]) -> typing.Tuple[LocalRuntime, bool]:
    """The runtime to use and whether this process owns it; an attach to our own live child returns that child."""
    if inference is not None and not runtime.owned and runtime.serves is None:
        raise ValueError(
            "a runtime of unknown inference already listens there; stop it or set HAI_AGENT_RUNTIME_PORT to another port"
        )
    with _spawned_lock:
        if runtime.owned:
            _spawned_here[runtime.base_url] = runtime
            return runtime, True
        spawned = _spawned_here.get(runtime.base_url)
        if spawned is not None and spawned.child_alive and spawned.api_key == runtime.api_key:
            return spawned, True
        _spawned_here.pop(runtime.base_url, None)
    return runtime, False

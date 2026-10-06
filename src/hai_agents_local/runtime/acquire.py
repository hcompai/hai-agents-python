"""The runtime behind ``Client.local``: a caller-provided one, or a shared-recipe runtime started for the client."""

from __future__ import annotations

import asyncio
import threading
import typing

from hai_agents.client import API_KEY_VAR, default_api_key

from .inference import Inference
from .runtime import LocalRuntime

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
    if inference is not None and not runtime.owned:
        raise ValueError("inference selection cannot reconfigure an existing runtime; choose a free local port")
    with _spawned_lock:
        if runtime.owned:
            _spawned_here[runtime.base_url] = runtime
            return runtime, True
        spawned = _spawned_here.get(runtime.base_url)
        if spawned is not None and spawned.child_alive and spawned.api_key == runtime.api_key:
            return spawned, True
        _spawned_here.pop(runtime.base_url, None)
    return runtime, False

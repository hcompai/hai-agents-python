"""The runtime behind ``Client.local``: a caller-provided one, or a shared-recipe runtime started for the client."""

from __future__ import annotations

import asyncio
import typing

from .inference import Inference
from .runtime import LocalRuntime

SHARED_RECIPE = "shared"
RECIPE_ENV = "HAI_AGENT_RUNTIME_RECIPE"


def acquire_runtime(
    runtime: typing.Optional[LocalRuntime],
    *,
    inference: typing.Optional[Inference],
    local_options: typing.Optional[typing.Dict[str, typing.Any]],
) -> typing.Tuple[LocalRuntime, bool]:
    """The runtime a local client talks to, and whether that client owns (and so stops) it."""
    if runtime is not None:
        _require_unconfigured(inference, local_options)
        runtime.require_recipe(SHARED_RECIPE)
        return runtime, False
    started = LocalRuntime.ensure_started(**_launch_options(inference, local_options))
    return started, _claim(started, inference)


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
    return started, _claim(started, inference)


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
    if inference is not None:
        options["spawn_env"] = inference.runtime_env(options["spawn_env"])
        options["inherit_env"] = False
    return options


def _claim(runtime: LocalRuntime, inference: typing.Optional[Inference]) -> bool:
    if inference is not None and not runtime.owned:
        raise ValueError("inference selection cannot reconfigure an existing runtime; choose a free local port")
    return runtime.owned

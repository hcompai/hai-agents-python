"""Spawns local bridges for user_device environments and stamps their session ids into the agent spec."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence, Union

from pydantic import BaseModel

from .bridge import LocalBridge, TokenSource
from .browser import SeleniumBrowserBridge
from .desktop import PyautoguiDesktopBridge

if TYPE_CHECKING:
    from hai_agents.types.agent import Agent

AgentLike = Union[str, "Agent", Mapping[str, Any]]
EnvironmentLike = Union[str, BaseModel, Mapping[str, Any]]

BRIDGE_TYPES: dict[str, type[LocalBridge]] = {
    SeleniumBrowserBridge.environment_kind: SeleniumBrowserBridge,
    PyautoguiDesktopBridge.environment_kind: PyautoguiDesktopBridge,
}


def localize_agent(
    agent: AgentLike, *, api_key: TokenSource, base_url: str | None = None
) -> tuple[AgentLike, list[LocalBridge]]:
    """Copy of the agent where every unclaimed user_device environment is stamped with the session id
    of a freshly built bridge, plus those bridges. Environments that already carry a session_id are
    assumed to be served elsewhere and left alone, as are string agent references."""
    bridges: list[LocalBridge] = []
    return _localize_agent(agent, bridges, api_key, base_url), bridges


def _localize_agent(
    agent: AgentLike, bridges: list[LocalBridge], api_key: TokenSource, base_url: str | None
) -> AgentLike:
    if isinstance(agent, str):
        return agent
    changes: dict[str, Any] = {}
    environments = _read(agent, "environments")
    if isinstance(environments, (list, tuple)):
        localized_envs = [_localize_environment(env, bridges, api_key, base_url) for env in environments]
        if _any_replaced(localized_envs, environments):
            changes["environments"] = localized_envs
    subagents = _read(agent, "subagents")
    if isinstance(subagents, (list, tuple)):
        localized_subs = [_localize_agent(sub, bridges, api_key, base_url) for sub in subagents]
        if _any_replaced(localized_subs, subagents):
            changes["subagents"] = localized_subs
    return _replace(agent, **changes) if changes else agent


def _localize_environment(
    env: EnvironmentLike, bridges: list[LocalBridge], api_key: TokenSource, base_url: str | None
) -> EnvironmentLike:
    kind = _local_kind(env)
    if kind is None or _read(env, "session_id"):
        return env
    if any(bridge.environment_kind == kind for bridge in bridges):
        raise ValueError(
            f"the agent tree has multiple user_device {kind} environments, but this machine can only "
            f"serve one local {kind}; give the extra environments an explicit session_id and serve each "
            "from its own machine with `hai local browser|desktop --session-id <id>`"
        )
    bridge = BRIDGE_TYPES[kind](_read(env, "id"), api_key=api_key, base_url=base_url)
    bridges.append(bridge)
    return _replace(env, kind=kind, session_id=bridge.session_id)


def _local_kind(env: EnvironmentLike) -> str | None:
    if _read(env, "host") != "user_device":
        return None
    kind = _read(env, "kind") or _model_kind(env) or "web"
    if kind not in BRIDGE_TYPES:
        raise ValueError(
            f"user_device environment {_read(env, 'id')!r} has kind {kind!r}, which cannot be served by a "
            f"local bridge; supported kinds: {sorted(BRIDGE_TYPES)}"
        )
    return kind


def _model_kind(env: EnvironmentLike) -> str | None:
    """The generated Browser/Desktop models carry no kind field; the class says which branch it is."""
    from hai_agents.types import Desktop

    return "desktop" if isinstance(env, Desktop) else None


def _any_replaced(localized: Sequence[Any], original: Sequence[Any]) -> bool:
    return any(new is not old for new, old in zip(localized, original))


def _read(obj: Any, key: str) -> Any:
    """The public API accepts agents/environments as dicts or generated models; read either shape."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _replace(obj: Any, **changes: Any) -> Any:
    """Copy-with-changes across both accepted shapes; anything else cannot carry a session_id."""
    if isinstance(obj, BaseModel):
        return obj.model_copy(update=changes)
    if isinstance(obj, dict):
        return {**obj, **changes}
    raise TypeError(
        f"cannot set {sorted(changes)} on {type(obj).__name__}; "
        "pass user_device agents and environments as dicts or generated models"
    )

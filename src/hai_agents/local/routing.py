"""Routes user_device environments to local bridges by stamping deterministic session ids."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence, Union

from pydantic import BaseModel

from .bridge import LocalBridge
from .browser import SeleniumBrowserBridge
from .desktop import PyautoguiDesktopBridge
from .utils import session_id_from_environment_id

if TYPE_CHECKING:
    from ..types.agent import Agent

AgentLike = Union[str, "Agent", Mapping[str, Any]]
EnvironmentLike = Union[str, BaseModel, Mapping[str, Any]]

BRIDGE_TYPES: dict[str, type[LocalBridge]] = {
    SeleniumBrowserBridge.environment_kind: SeleniumBrowserBridge,
    PyautoguiDesktopBridge.environment_kind: PyautoguiDesktopBridge,
}


class SessionRouter:
    """Stamps user_device environments with deterministic session ids and builds their local bridges."""

    def __init__(self, get_api_key: Callable[[], str], base_url: str | None = None) -> None:
        self._get_api_key = get_api_key
        self._base_url = base_url

    def stamp_agent(self, agent: AgentLike) -> AgentLike:
        if isinstance(agent, str):
            return agent
        changes: dict[str, Any] = {}
        environments = _read(agent, "environments")
        if environments:
            stamped = self.stamp_environments(environments)
            if _any_replaced(stamped, environments):
                changes["environments"] = stamped
        subagents = _read(agent, "subagents")
        if subagents:
            stamped = self.stamp_subagents(subagents)
            if _any_replaced(stamped, subagents):
                changes["subagents"] = stamped
        return _replace(agent, **changes) if changes else agent

    def stamp_environments(self, environments: Sequence[EnvironmentLike]) -> Sequence[EnvironmentLike]:
        if not isinstance(environments, (list, tuple)):
            return environments
        return [self._stamp_environment(env) for env in environments]

    def stamp_subagents(self, subagents: Sequence[AgentLike]) -> Sequence[AgentLike]:
        if not isinstance(subagents, (list, tuple)):
            return subagents
        return [self.stamp_agent(sub) for sub in subagents]

    def stamp_agent_kwargs(self, kwargs: dict[str, Any]) -> None:
        if kwargs.get("environments"):
            kwargs["environments"] = self.stamp_environments(kwargs["environments"])
        if kwargs.get("subagents"):
            kwargs["subagents"] = self.stamp_subagents(kwargs["subagents"])

    def bridges_for_agent(
        self, agent: AgentLike, fetch_agent: Callable[[str], AgentLike | None] | None = None
    ) -> list[LocalBridge]:
        """Bridges for every user_device environment in the tree; fetch_agent resolves string subagents."""
        bridges: list[LocalBridge] = []
        for env in _read(agent, "environments") or ():
            target = _local_target(env)
            if target is None:
                continue
            kind, env_id = target
            session_id = _read(env, "session_id")
            if not session_id:
                raise RuntimeError(
                    f"user_device environment {env_id!r} has no session_id, so sessions cannot route commands "
                    "to the local bridge; create or patch the agent with this SDK to set it"
                )
            bridges.append(
                BRIDGE_TYPES[kind](env_id, api_key=self._get_api_key(), base_url=self._base_url, session_id=session_id)
            )
        for sub in _read(agent, "subagents") or ():
            if isinstance(sub, str):
                resolved = fetch_agent(sub) if fetch_agent is not None else None
                if resolved is None:
                    continue
                sub = resolved
            bridges.extend(self.bridges_for_agent(sub, fetch_agent))
        return bridges

    def _stamp_environment(self, env: EnvironmentLike) -> EnvironmentLike:
        target = _local_target(env)
        if target is None or _read(env, "session_id"):
            return env
        kind, env_id = target
        return _replace(env, session_id=session_id_from_environment_id(env_id, self._get_api_key(), kind))


def subagent_names(agent: AgentLike) -> list[str]:
    """Names of subagents referenced by registration rather than defined inline, at any depth."""
    names: list[str] = []
    for sub in _read(agent, "subagents") or ():
        if isinstance(sub, str):
            names.append(sub)
        else:
            names.extend(subagent_names(sub))
    return names


def _any_replaced(stamped: Any, original: Any) -> bool:
    if stamped is original:
        return False
    return any(new is not old for new, old in zip(stamped, original))


def _local_target(env: EnvironmentLike) -> tuple[str, str] | None:
    if _read(env, "host") != "user_device":
        return None
    kind = _read(env, "kind") or "web"
    env_id = _read(env, "id")
    if kind not in BRIDGE_TYPES:
        raise ValueError(
            f"user_device environment {env_id!r} has kind {kind!r}, which cannot be served by a local "
            f"bridge; supported kinds: {sorted(BRIDGE_TYPES)}"
        )
    if not env_id:
        raise ValueError("user_device environments need an id to derive their local session")
    return kind, env_id


def _read(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _replace(obj: Any, **changes: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_copy(update=changes)
    if isinstance(obj, dict):
        return {**obj, **changes}
    raise TypeError(
        f"cannot set {sorted(changes)} on {type(obj).__name__}; "
        "pass user_device agents and environments as dicts or generated models"
    )

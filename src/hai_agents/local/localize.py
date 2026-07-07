from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from .bridge import LocalBridge, session_id_from_environment_id
from .browser import SeleniumBrowserBridge
from .desktop import PyautoguiDesktopBridge

BRIDGE_TYPES: dict[str, type[LocalBridge]] = {
    SeleniumBrowserBridge.environment_kind: SeleniumBrowserBridge,
    PyautoguiDesktopBridge.environment_kind: PyautoguiDesktopBridge,
}


class AgentLocalizer:
    """Stamps user_device environments with deterministic session ids and builds their local bridges."""

    def __init__(self, get_api_key: Callable[[], str], base_url: str | None = None) -> None:
        self._get_api_key = get_api_key
        self._base_url = base_url

    def localize_agent(self, agent: Any) -> Any:
        changes: dict[str, Any] = {}
        environments = _read(agent, "environments")
        if environments:
            localized = self.localize_environments(environments)
            if _any_replaced(localized, environments):
                changes["environments"] = localized
        subagents = _read(agent, "subagents")
        if subagents:
            localized = self.localize_subagents(subagents)
            if _any_replaced(localized, subagents):
                changes["subagents"] = localized
        return _replace(agent, **changes) if changes else agent

    def localize_environments(self, environments: Any) -> Any:
        if not isinstance(environments, (list, tuple)):
            return environments
        return [self._localize_environment(env) for env in environments]

    def localize_subagents(self, subagents: Any) -> Any:
        if not isinstance(subagents, (list, tuple)):
            return subagents
        return [self.localize_agent(sub) for sub in subagents]

    def localize_agent_kwargs(self, kwargs: dict[str, Any]) -> None:
        if kwargs.get("environments"):
            kwargs["environments"] = self.localize_environments(kwargs["environments"])
        if kwargs.get("subagents"):
            kwargs["subagents"] = self.localize_subagents(kwargs["subagents"])

    def bridges_for_agent(self, agent: Any, fetch_agent: Callable[[str], Any] | None = None) -> list[LocalBridge]:
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
                sub = fetch_agent(sub) if fetch_agent is not None else None
                if sub is None:
                    continue
            bridges.extend(self.bridges_for_agent(sub, fetch_agent))
        return bridges

    def _localize_environment(self, env: Any) -> Any:
        target = _local_target(env)
        if target is None or _read(env, "session_id"):
            return env
        kind, env_id = target
        return _replace(env, session_id=session_id_from_environment_id(env_id, self._get_api_key(), kind))


def subagent_names(agent: Any) -> list[str]:
    """Names of subagents referenced by registration rather than defined inline, at any depth."""
    names: list[str] = []
    for sub in _read(agent, "subagents") or ():
        if isinstance(sub, str):
            names.append(sub)
        else:
            names.extend(subagent_names(sub))
    return names


def _any_replaced(localized: Any, original: Any) -> bool:
    if localized is original:
        return False
    return any(new is not old for new, old in zip(localized, original))


def _local_target(env: Any) -> tuple[str, str] | None:
    if _read(env, "host") != "user_device":
        return None
    kind = _read(env, "kind") or "web"
    env_id = _read(env, "id")
    return (kind, env_id) if kind in BRIDGE_TYPES and env_id else None


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

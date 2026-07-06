from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from .bridge import LocalBridge, session_id_from_environment_id
from .browser import BrowserBridge
from .desktop import DesktopBridge

BRIDGE_TYPES: dict[str, type[LocalBridge]] = {
    BrowserBridge.capability: BrowserBridge,
    DesktopBridge.capability: DesktopBridge,
}
KIND_TO_CAPABILITY = {"web": BrowserBridge.capability, "desktop": DesktopBridge.capability}


def localize_environments(environments: Any, get_api_key: Callable[[], str]) -> Any:
    if not isinstance(environments, (list, tuple)):
        return environments
    return [_localize_environment(env, get_api_key) for env in environments]


def localize_subagents(subagents: Any, get_api_key: Callable[[], str]) -> Any:
    if not isinstance(subagents, (list, tuple)):
        return subagents
    return [localize_agent(sub, get_api_key) for sub in subagents]


def localize_agent(agent: Any, get_api_key: Callable[[], str]) -> Any:
    changes: dict[str, Any] = {}
    environments = _read(agent, "environments")
    if environments:
        changes["environments"] = localize_environments(environments, get_api_key)
    subagents = _read(agent, "subagents")
    if subagents:
        changes["subagents"] = localize_subagents(subagents, get_api_key)
    return _replace(agent, **changes) if changes else agent


def _local_target(env: Any) -> tuple[str, str] | None:
    if _read(env, "host") != "user_device":
        return None
    capability = KIND_TO_CAPABILITY.get(_read(env, "kind") or "web")
    env_id = _read(env, "id")
    return (capability, env_id) if capability and env_id else None


def _localize_environment(env: Any, get_api_key: Callable[[], str]) -> Any:
    target = _local_target(env)
    if target is None or _read(env, "session_id"):
        return env
    capability, env_id = target
    return _replace(env, session_id=session_id_from_environment_id(env_id, get_api_key(), capability))


def bridges_for_agent(agent: Any, api_key: str, base_url: str) -> list[LocalBridge]:
    bridges: list[LocalBridge] = []
    for env in _read(agent, "environments") or ():
        target = _local_target(env)
        if target is None:
            continue
        capability, env_id = target
        session_id = _read(env, "session_id")
        if not session_id:
            raise RuntimeError(
                f"user_device environment {env_id!r} has no session_id, so sessions cannot route commands "
                "to the local bridge; create or patch the agent with this SDK to set it"
            )
        bridges.append(BRIDGE_TYPES[capability](env_id, api_key=api_key, base_url=base_url, session_id=session_id))
    for sub in _read(agent, "subagents") or ():
        bridges.extend(bridges_for_agent(sub, api_key, base_url))
    return bridges


def _read(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _replace(obj: Any, **changes: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_copy(update=changes)
    if isinstance(obj, dict):
        return {**obj, **changes}
    return obj

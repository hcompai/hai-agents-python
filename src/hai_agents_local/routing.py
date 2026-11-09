"""Spawns bridges for environments on this machine: inline ones are stamped, named ones routed by overrides."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any, Collection, Literal, Mapping, NamedTuple, Sequence, Union

from pydantic import BaseModel

from .bridge import LocalBridge, TokenSource
from .browser import SeleniumBrowserBridge
from .desktop import PyautoguiDesktopBridge
from .workstation import WorkstationBridge

if TYPE_CHECKING:
    from hai_agents.types.agent import Agent

AgentLike = Union[str, "Agent", Mapping[str, Any]]
EnvironmentLike = Union[str, BaseModel, Mapping[str, Any]]
Reference = tuple[Literal["agent", "environment"], str]

BRIDGE_TYPES: dict[str, type[LocalBridge]] = {
    SeleniumBrowserBridge.environment_kind: SeleniumBrowserBridge,
    PyautoguiDesktopBridge.environment_kind: PyautoguiDesktopBridge,
    WorkstationBridge.environment_kind: WorkstationBridge,
}


class Localized(NamedTuple):
    agent: AgentLike
    bridges: list[LocalBridge]
    overrides: dict[str, str]


def references(agent: AgentLike) -> list[Reference]:
    """Names in the caller's agent tree whose specs decide whether a bridge is needed."""
    if isinstance(agent, str):
        return [("agent", agent)]
    found: list[Reference] = [
        ("environment", env) for env in _read(agent, "environments") or [] if isinstance(env, str)
    ]
    for sub in _read(agent, "subagents") or []:
        found += references(sub)
    return found


def split_revision(reference: str) -> tuple[str, int | None]:
    """``name:N`` pins a revision; any other colon is part of the name."""
    name, sep, revision = reference.rpartition(":")
    return (name, int(revision)) if sep and revision.isdigit() else (reference, None)


def local_bridge_types(agent: AgentLike, resolved: Mapping[Reference, Any] | None = None) -> list[type[LocalBridge]]:
    """The bridges this machine serves ``agent``'s environments with, whether or not a session already binds them."""
    resolved = resolved or {}
    if isinstance(agent, str):
        spec = resolved.get(("agent", agent))
        return [] if spec is None else local_bridge_types(spec, resolved)
    found: list[type[LocalBridge]] = []
    for env in _read(agent, "environments") or []:
        spec = resolved.get(("environment", env)) if isinstance(env, str) else env
        kind = None if spec is None else _local_kind(spec)
        if kind is not None:
            found.append(_bridge_type(spec, kind))
    for sub in _read(agent, "subagents") or []:
        found += local_bridge_types(sub, resolved)
    return found


def localize_agent(
    agent: AgentLike,
    *,
    api_key: TokenSource,
    base_url: str | None = None,
    resolved: Mapping[Reference, Any] | None = None,
    claimed: Collection[str] = (),
    seed: str | None = None,
) -> Localized:
    """Bridges for unclaimed user_device envs; a ``seed`` makes their session ids reproducible across retries."""
    walk = _Walk(api_key, base_url, resolved or {}, frozenset(claimed), seed)
    return Localized(walk.agent(agent, "agent", by_name=False), walk.bridges, walk.overrides)


class _Walk:
    def __init__(
        self,
        api_key: TokenSource,
        base_url: str | None,
        resolved: Mapping[Reference, Any],
        claimed: frozenset[str],
        seed: str | None,
    ) -> None:
        self.api_key, self.base_url, self.resolved, self.claimed, self.seed = api_key, base_url, resolved, claimed, seed
        self.bridges: list[LocalBridge] = []
        self.overrides: dict[str, str] = {}

    def agent(self, agent: AgentLike, path: str, *, by_name: bool) -> AgentLike:
        if isinstance(agent, str):
            spec = self.resolved.get(("agent", agent))
            if spec is not None:
                self.agent(spec, path, by_name=True)
            return agent
        changes: dict[str, Any] = {}
        environments = _read(agent, "environments")
        if isinstance(environments, (list, tuple)):
            localized_envs = [self.environment(env, path, environments, by_name=by_name) for env in environments]
            if _any_replaced(localized_envs, environments):
                changes["environments"] = localized_envs
        subagents = _read(agent, "subagents")
        if isinstance(subagents, (list, tuple)):
            localized_subs = [self.agent(sub, _subagent_path(path, sub), by_name=by_name) for sub in subagents]
            if _any_replaced(localized_subs, subagents):
                changes["subagents"] = localized_subs
        return _replace(agent, **changes) if changes else agent

    def environment(
        self, env: EnvironmentLike, path: str, siblings: Sequence[Any], *, by_name: bool
    ) -> EnvironmentLike:
        if isinstance(env, str):
            spec = self.resolved.get(("environment", env))
            if spec is not None:
                self.environment(spec, path, [self.lookup(sibling) for sibling in siblings], by_name=True)
            return env
        kind = _local_kind(env)
        if kind is None or _read(env, "session_id"):
            return env
        key = f"{path}.environments[kind={kind}].session_id"
        if any(key == claim or key.startswith(f"{claim}.") for claim in self.claimed):
            return env
        serve = SERVE_COMMANDS[_bridge_type(env, kind).environment_kind]
        if not by_name:
            return _replace(env, kind=kind, session_id=self.bridge(env, kind).session_id)
        if sum(_kind(sibling) == kind for sibling in siblings) > 1:
            raise ValueError(
                f"{path} has several {kind} environments, so the platform cannot route its local {kind} "
                f"by kind; give it an explicit session_id and serve it with `{serve} --session-id <id>`"
            )
        if not all(_SEGMENT.match(segment) for segment in key.split(".")):
            raise ValueError(
                f"cannot route the local {kind} at {path}: override paths split on dots, so a subagent "
                f"name with '.', '[' or ']' cannot be addressed; rename it, or give the environment an explicit "
                f"session_id and serve it with `{serve} --session-id <id>`"
            )
        self.overrides[key] = self.bridge(env, kind).session_id
        return env

    def lookup(self, env: EnvironmentLike) -> Any:
        return self.resolved.get(("environment", env), env) if isinstance(env, str) else env

    def bridge(self, env: EnvironmentLike, kind: str) -> LocalBridge:
        bridge_type = _bridge_type(env, kind)
        if any(type(bridge) is bridge_type for bridge in self.bridges):
            raise ValueError(
                f"the agent tree has multiple local {kind} environments that this machine would serve the same "
                "way, but it can only serve one; give the extra environments an explicit session_id and serve "
                f"each from its own machine with `{SERVE_COMMANDS[bridge_type.environment_kind]} --session-id <id>`"
            )
        seed = f"{self.seed}:{bridge_type.environment_kind}"
        session_id = None if self.seed is None else str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
        options: dict[str, Any] = {}
        width = _read(env, "screenshot_max_width")
        if bridge_type is WorkstationBridge and width:
            options["environment_variables"] = {"WEB_MAX_IMAGE_WIDTH": str(width), "DESK_MAX_IMAGE_WIDTH": str(width)}
        bridge = bridge_type(
            _read(env, "id"), api_key=self.api_key, base_url=self.base_url, session_id=session_id, **options
        )
        self.bridges.append(bridge)
        return bridge


SERVE_COMMANDS = {
    SeleniumBrowserBridge.environment_kind: "holo local browser",
    PyautoguiDesktopBridge.environment_kind: "holo local desktop",
    WorkstationBridge.environment_kind: "holo local desktop --shell",
}
_SEGMENT = re.compile(r"^[A-Za-z_]\w*(?:\[[^\[\]]+\])?$")


def _subagent_path(path: str, sub: AgentLike) -> str:
    name = split_revision(sub)[0] if isinstance(sub, str) else _read(sub, "name")
    return f"{path}.subagents[name={name}]"


def _kind(env: Any) -> str | None:
    if isinstance(env, str):
        return None
    return _read(env, "kind") or _model_kind(env) or "web"


def _local_kind(env: EnvironmentLike) -> str | None:
    """The kind of ``env`` when this machine serves it: a desktop always, a browser or workstation on user_device."""
    kind = _kind(env)
    if kind == "desktop":
        return kind
    if _read(env, "host") != "user_device":
        return None
    if kind not in BRIDGE_TYPES:
        raise ValueError(
            f"user_device environment {_read(env, 'id')!r} has kind {kind!r}, which cannot be served by a "
            f"local bridge; supported kinds: {sorted(BRIDGE_TYPES)}"
        )
    return kind


def _bridge_type(env: EnvironmentLike, kind: str) -> type[LocalBridge]:
    if kind == "desktop" and _read(_read(env, "mode"), "type") == "shell":
        return WorkstationBridge
    return BRIDGE_TYPES[kind]


def _model_kind(env: EnvironmentLike) -> str | None:
    """The generated environment models carry no kind field; the class says which branch it is."""
    from hai_agents.types import Desktop, Workstation

    if isinstance(env, Desktop):
        return "desktop"
    if isinstance(env, Workstation):
        return "workstation"
    return None


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

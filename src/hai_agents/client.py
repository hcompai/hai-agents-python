"""Client classes extended with create-and-run convenience methods.

Fern emits the API surface as ``BaseClient``/``AsyncBaseClient``; these thin
subclasses add the object-oriented sugar (``run_session``, ``start_session``,
``session``) that delegates to the hand-written polling helpers.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import typing

import typing_extensions

from .base_client import AsyncBaseClient, BaseClient
from .local.bridge import LocalBridge
from .local.config import auto_bridges_enabled
from .local.manager import ensure_bridges, stop_bridges
from .local.routing import localize_agent
from .polling import (
    AnswerT,
    AsyncSessionHandle,
    CreateSessionParams,
    SessionHandle,
    SessionRunResult,
    _attach_answer_schema,
    _attach_tool_definitions,
    assert_request_under_limit,
)
from .polling import async_run_session as _async_run_session
from .polling import run_session as _run_session
from .sessions.client import AsyncSessionsClient, SessionsClient
from .tools import ToolInput, as_tools

logger = logging.getLogger(__name__)


def _warn_if_overrides_target_user_device(kwargs: typing.Dict[str, typing.Any]) -> None:
    overrides = kwargs.get("overrides")
    if overrides and "user_device" in json.dumps(overrides, default=str):
        logger.warning(
            "session overrides mention user_device, but auto-started bridges are derived from the agent "
            "spec only; serve override-injected environments manually with `hai local browser|desktop`"
        )


def _localize(client_wrapper: typing.Any, kwargs: typing.Dict[str, typing.Any]) -> typing.List["LocalBridge"]:
    """Spawn bridges for unclaimed user_device environments in an inline agent and stamp their session ids.

    String agent references are left alone: registered agents must carry an explicit session_id on their
    user_device environments, served manually with `hai local browser|desktop`.
    """
    agent = kwargs.get("agent")
    if agent is None or isinstance(agent, str) or not auto_bridges_enabled():
        return []
    _warn_if_overrides_target_user_device(kwargs)
    token_source = getattr(client_wrapper, "_async_token", None) or client_wrapper._get_api_key
    localized, bridges = localize_agent(agent, api_key=token_source, base_url=client_wrapper.get_base_url())
    kwargs["agent"] = localized
    return bridges


def _cancel_session_on_crash(
    client_wrapper: typing.Any, bridges: typing.Sequence["LocalBridge"], session: typing.Any
) -> None:
    """A bridge that dies mid-session leaves the agent without local control; cancel the session then."""
    session_id = getattr(session, "id", None)
    if session_id is None:
        return

    def cancel() -> None:
        logger.error("local bridge for session %s crashed; cancelling the session", session_id)
        try:
            client = Client(api_key=client_wrapper._get_api_key(), base_url=client_wrapper.get_base_url())
            client.sessions.cancel_session(session_id)
        except Exception:
            logger.exception("failed to cancel session %s after its local bridge crashed", session_id)

    for bridge in bridges:
        bridge.on_crash = cancel


class _LocalSessionsClient(SessionsClient):
    @functools.wraps(SessionsClient.create_session)
    def create_session(self, **kwargs: typing.Any) -> typing.Any:
        wrapper = self._raw_client._client_wrapper
        bridges = _localize(wrapper, kwargs)
        started = ensure_bridges(bridges)
        try:
            session = super().create_session(**kwargs)
        except BaseException:
            stop_bridges(started)
            raise
        _cancel_session_on_crash(wrapper, bridges, session)
        return session


class _LocalAsyncSessionsClient(AsyncSessionsClient):
    @functools.wraps(AsyncSessionsClient.create_session)
    async def create_session(self, **kwargs: typing.Any) -> typing.Any:
        wrapper = self._raw_client._client_wrapper
        bridges = _localize(wrapper, kwargs)
        started = await asyncio.to_thread(ensure_bridges, bridges)
        try:
            session = await super().create_session(**kwargs)
        except BaseException:
            await asyncio.to_thread(stop_bridges, started)
            raise
        _cancel_session_on_crash(wrapper, bridges, session)
        return session


class Client(BaseClient):
    def run_session(
        self,
        *,
        wait_for_seconds: int = 20,
        include_events: bool = True,
        timeout_seconds: typing.Optional[float] = None,
        poll_backoff_seconds: float = 0.0,
        max_polls: typing.Optional[int] = None,
        answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
        tools: typing.Optional[typing.Sequence[ToolInput]] = None,
        **create_params: typing_extensions.Unpack[CreateSessionParams],
    ) -> SessionRunResult[AnswerT]:
        """Create a session and block until it completes, returning the result and final answer."""
        return _run_session(
            self,
            wait_for_seconds=wait_for_seconds,
            include_events=include_events,
            timeout_seconds=timeout_seconds,
            poll_backoff_seconds=poll_backoff_seconds,
            max_polls=max_polls,
            answer_schema=answer_schema,
            tools=tools,
            **create_params,
        )

    def start_session(
        self,
        *,
        answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
        tools: typing.Optional[typing.Sequence[ToolInput]] = None,
        **create_params: typing_extensions.Unpack[CreateSessionParams],
    ) -> SessionHandle[AnswerT]:
        """Create a session and return a handle to it without waiting."""
        normalized_tools = as_tools(tools) if tools else None
        params: typing.Dict[str, typing.Any] = dict(create_params)
        if normalized_tools:
            _attach_tool_definitions(params, normalized_tools)
        if answer_schema is not None:
            _attach_answer_schema(params, answer_schema)
        assert_request_under_limit(params)
        session = self.sessions.create_session(**params)
        return SessionHandle(self, session.id, answer_schema=answer_schema, tools=normalized_tools)

    def session(self, id: str) -> SessionHandle:
        """Wrap an existing session id in a handle."""
        return SessionHandle(self, id)

    @property
    def sessions(self) -> _LocalSessionsClient:
        if self._sessions is None:
            self._sessions = _LocalSessionsClient(client_wrapper=self._client_wrapper)
        return self._sessions


class AsyncClient(AsyncBaseClient):
    async def run_session(
        self,
        *,
        wait_for_seconds: int = 20,
        include_events: bool = True,
        timeout_seconds: typing.Optional[float] = None,
        poll_backoff_seconds: float = 0.0,
        max_polls: typing.Optional[int] = None,
        answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
        tools: typing.Optional[typing.Sequence[ToolInput]] = None,
        **create_params: typing_extensions.Unpack[CreateSessionParams],
    ) -> SessionRunResult[AnswerT]:
        """Create a session and block until it completes, returning the result and final answer."""
        return await _async_run_session(
            self,
            wait_for_seconds=wait_for_seconds,
            include_events=include_events,
            timeout_seconds=timeout_seconds,
            poll_backoff_seconds=poll_backoff_seconds,
            max_polls=max_polls,
            answer_schema=answer_schema,
            tools=tools,
            **create_params,
        )

    async def start_session(
        self,
        *,
        answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
        tools: typing.Optional[typing.Sequence[ToolInput]] = None,
        **create_params: typing_extensions.Unpack[CreateSessionParams],
    ) -> AsyncSessionHandle[AnswerT]:
        """Create a session and return a handle to it without waiting."""
        normalized_tools = as_tools(tools) if tools else None
        params: typing.Dict[str, typing.Any] = dict(create_params)
        if normalized_tools:
            _attach_tool_definitions(params, normalized_tools)
        if answer_schema is not None:
            _attach_answer_schema(params, answer_schema)
        assert_request_under_limit(params)
        session = await self.sessions.create_session(**params)
        return AsyncSessionHandle(self, session.id, answer_schema=answer_schema, tools=normalized_tools)

    def session(self, id: str) -> AsyncSessionHandle:
        """Wrap an existing session id in a handle."""
        return AsyncSessionHandle(self, id)

    @property
    def sessions(self) -> _LocalAsyncSessionsClient:
        if self._sessions is None:
            self._sessions = _LocalAsyncSessionsClient(client_wrapper=self._client_wrapper)
        return self._sessions

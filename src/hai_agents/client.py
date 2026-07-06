"""Client classes extended with create-and-run convenience methods.

Fern emits the API surface as ``BaseClient``/``AsyncBaseClient``; these thin
subclasses add the object-oriented sugar (``run_session``, ``start_session``,
``session``) that delegates to the hand-written polling helpers.
"""

from __future__ import annotations

import asyncio
import functools
import typing

import typing_extensions

from .agents.client import AgentsClient, AsyncAgentsClient
from .base_client import AsyncBaseClient, BaseClient
from .local.manager import auto_bridges_enabled, ensure_bridges
from .local.wiring import bridges_for_agent, localize_agent, localize_environments, localize_subagents
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


def _wire_agent_fields(kwargs: typing.Dict[str, typing.Any], get_api_key: typing.Callable[[], str]) -> None:
    if kwargs.get("environments"):
        kwargs["environments"] = localize_environments(kwargs["environments"], get_api_key)
    if kwargs.get("subagents"):
        kwargs["subagents"] = localize_subagents(kwargs["subagents"], get_api_key)


def _start_local_bridges(agent: typing.Any, client_wrapper: typing.Any) -> None:
    ensure_bridges(bridges_for_agent(agent, client_wrapper._get_api_key(), client_wrapper.get_base_url()))


class _LocalAgentsClient(AgentsClient):
    @functools.wraps(AgentsClient.create_agent)
    def create_agent(self, **kwargs: typing.Any) -> typing.Any:
        _wire_agent_fields(kwargs, self._raw_client._client_wrapper._get_api_key)
        return super().create_agent(**kwargs)

    @functools.wraps(AgentsClient.update_agent)
    def update_agent(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        _wire_agent_fields(kwargs, self._raw_client._client_wrapper._get_api_key)
        return super().update_agent(*args, **kwargs)

    @functools.wraps(AgentsClient.patch_agent)
    def patch_agent(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        _wire_agent_fields(kwargs, self._raw_client._client_wrapper._get_api_key)
        return super().patch_agent(*args, **kwargs)


class _LocalSessionsClient(SessionsClient):
    @functools.wraps(SessionsClient.create_session)
    def create_session(self, **kwargs: typing.Any) -> typing.Any:
        if "agent" in kwargs:
            wrapper = self._raw_client._client_wrapper
            kwargs["agent"] = localize_agent(kwargs["agent"], wrapper._get_api_key)
            agent = kwargs["agent"]
            if auto_bridges_enabled():
                if isinstance(agent, str):
                    agent = AgentsClient(client_wrapper=wrapper).get_agent(agent, resolve=True)
                _start_local_bridges(agent, wrapper)
        return super().create_session(**kwargs)


class _LocalAsyncAgentsClient(AsyncAgentsClient):
    @functools.wraps(AsyncAgentsClient.create_agent)
    async def create_agent(self, **kwargs: typing.Any) -> typing.Any:
        _wire_agent_fields(kwargs, self._raw_client._client_wrapper._get_api_key)
        return await super().create_agent(**kwargs)

    @functools.wraps(AsyncAgentsClient.update_agent)
    async def update_agent(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        _wire_agent_fields(kwargs, self._raw_client._client_wrapper._get_api_key)
        return await super().update_agent(*args, **kwargs)

    @functools.wraps(AsyncAgentsClient.patch_agent)
    async def patch_agent(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        _wire_agent_fields(kwargs, self._raw_client._client_wrapper._get_api_key)
        return await super().patch_agent(*args, **kwargs)


class _LocalAsyncSessionsClient(AsyncSessionsClient):
    @functools.wraps(AsyncSessionsClient.create_session)
    async def create_session(self, **kwargs: typing.Any) -> typing.Any:
        if "agent" in kwargs:
            wrapper = self._raw_client._client_wrapper
            kwargs["agent"] = localize_agent(kwargs["agent"], wrapper._get_api_key)
            agent = kwargs["agent"]
            if auto_bridges_enabled():
                if isinstance(agent, str):
                    agent = await AsyncAgentsClient(client_wrapper=wrapper).get_agent(agent, resolve=True)
                await asyncio.to_thread(_start_local_bridges, agent, wrapper)
        return await super().create_session(**kwargs)


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
    def agents(self) -> _LocalAgentsClient:
        if self._agents is None:
            self._agents = _LocalAgentsClient(client_wrapper=self._client_wrapper)
        return self._agents

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
    def agents(self) -> _LocalAsyncAgentsClient:
        if self._agents is None:
            self._agents = _LocalAsyncAgentsClient(client_wrapper=self._client_wrapper)
        return self._agents

    @property
    def sessions(self) -> _LocalAsyncSessionsClient:
        if self._sessions is None:
            self._sessions = _LocalAsyncSessionsClient(client_wrapper=self._client_wrapper)
        return self._sessions

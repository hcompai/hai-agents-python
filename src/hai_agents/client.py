"""Client classes extended with create-and-run convenience methods.

Fern emits the API surface as ``BaseClient``/``AsyncBaseClient``; these thin
subclasses add the object-oriented sugar (``run_session``, ``start_session``,
``session``) that delegates to the hand-written polling helpers.
"""

from __future__ import annotations

import typing

import pydantic
import typing_extensions

from .base_client import AsyncBaseClient, BaseClient
from .polling import (
    AnswerT,
    AsyncSessionHandle,
    CreateSessionParams,
    SessionHandle,
    SessionRunResult,
    _attach_answer_schema,
    assert_request_under_limit,
)
from .polling import async_run_session as _async_run_session
from .polling import run_session as _run_session


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
            **create_params,
        )

    def start_session(
        self,
        *,
        answer_schema: typing.Optional[typing.Type[pydantic.BaseModel]] = None,
        **create_params: typing_extensions.Unpack[CreateSessionParams],
    ) -> SessionHandle:
        """Create a session and return a handle to it without waiting."""
        params: typing.Dict[str, typing.Any] = dict(create_params)
        if answer_schema is not None:
            _attach_answer_schema(params, answer_schema)
        assert_request_under_limit(params)
        session = self.sessions.create_session(**params)
        return SessionHandle(self, session.id, answer_schema=answer_schema)

    def session(self, id: str) -> SessionHandle:
        """Wrap an existing session id in a handle."""
        return SessionHandle(self, id)


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
            **create_params,
        )

    async def start_session(
        self,
        *,
        answer_schema: typing.Optional[typing.Type[pydantic.BaseModel]] = None,
        **create_params: typing_extensions.Unpack[CreateSessionParams],
    ) -> AsyncSessionHandle:
        """Create a session and return a handle to it without waiting."""
        params: typing.Dict[str, typing.Any] = dict(create_params)
        if answer_schema is not None:
            _attach_answer_schema(params, answer_schema)
        assert_request_under_limit(params)
        session = await self.sessions.create_session(**params)
        return AsyncSessionHandle(self, session.id, answer_schema=answer_schema)

    def session(self, id: str) -> AsyncSessionHandle:
        """Wrap an existing session id in a handle."""
        return AsyncSessionHandle(self, id)

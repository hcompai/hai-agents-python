"""Client classes extended with create-and-run convenience methods.

Fern emits the API surface as ``BaseClient``/``AsyncBaseClient``; these thin
subclasses add the object-oriented sugar (``run_session``, ``start_session``,
``session``) that delegates to the hand-written polling helpers, and default
``api_key`` to the key ``hai login`` stored.
"""

from __future__ import annotations

import asyncio
import functools
import os
import typing
from pathlib import Path

import typing_extensions

from .base_client import AsyncBaseClient, BaseClient
from .core.api_error import ApiError
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

if typing.TYPE_CHECKING:
    from hai_agents_local.runtime import Inference, LocalRuntime
    from hai_agents_local.runtime.acquire import RuntimeHold

API_KEY_VAR = "HAI_API_KEY"

_P = typing_extensions.ParamSpec("_P")


def credentials_path() -> Path:
    """The global `.env` that `hai login` writes: `$XDG_CONFIG_HOME/hai/.env`, else `~/.config/hai/.env`."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "hai" / ".env"


def _stored_api_key() -> typing.Optional[str]:
    """The `HAI_API_KEY` that `hai login` stored, if any."""
    try:
        lines = credentials_path().read_text(encoding="utf-8").splitlines()
    except (OSError, RuntimeError, UnicodeDecodeError):
        return None
    for line in lines:
        name, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and name.strip() == API_KEY_VAR:
            return value.strip().strip("'\"") or None
    return None


def default_api_key() -> typing.Optional[str]:
    """`HAI_API_KEY`, else the key stored by `hai login`."""
    return os.getenv(API_KEY_VAR) or _stored_api_key()


def _default_api_key(init: typing.Callable[_P, None]) -> typing.Callable[_P, None]:
    """Resolve `api_key` as: argument, then `HAI_API_KEY`, then the key stored by `hai login`."""

    @functools.wraps(init)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        if kwargs.get("api_key") is None:
            api_key = default_api_key()
            if api_key is None:
                raise ApiError(body=f"No API key found. Pass api_key, set {API_KEY_VAR}, or run `hai login`.")
            kwargs["api_key"] = api_key
        init(*args, **kwargs)

    return wrapper


class _LocalRuntimeAccess:
    """The runtime behind a local client, read through its hold so a re-acquired runtime shows up everywhere."""

    _hold: typing.Optional[RuntimeHold] = None
    _auto_bridges = True

    @property
    def local_runtime(self) -> typing.Optional[LocalRuntime]:
        return None if self._hold is None else self._hold.runtime

    @property
    def _owns_runtime(self) -> bool:
        return self._hold is not None and self._hold.owned


class Client(_LocalRuntimeAccess, BaseClient):
    __init__ = _default_api_key(BaseClient.__init__)

    @classmethod
    def local(
        cls,
        *,
        runtime: typing.Optional[LocalRuntime] = None,
        inference: typing.Optional[Inference] = None,
        local_options: typing.Optional[typing.Dict[str, typing.Any]] = None,
        auto_bridges: bool = True,
        timeout: typing.Optional[float] = None,
    ) -> Client:
        """A client on a local agent runtime: ``runtime`` if given, else one this client starts and owns."""
        from hai_agents_local.runtime.acquire import RuntimeHold

        hold = RuntimeHold.acquire(runtime, inference=inference, local_options=local_options)
        try:
            client = cls(base_url=hold.runtime.base_url, api_key=hold.api_key, httpx_client=hold.http_client(timeout))
        except BaseException:
            if hold.owned:
                hold.runtime.shutdown()
            raise
        client._hold, client._auto_bridges = hold, auto_bridges
        return client

    def close(self) -> None:
        """Stop sessions this client bridged; a local client also stops its runtime once no other client uses it."""
        try:
            if self._sessions is not None:
                self._sessions.close()
        finally:
            if self.local_runtime is not None:
                try:
                    if self._owns_runtime:
                        self.local_runtime.shutdown_if_idle(getattr(self._sessions, "own_session_ids", ()))
                finally:
                    self._client_wrapper.httpx_client.httpx_client.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: typing.Any) -> None:
        self.close()

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
    def sessions(self) -> SessionsClient:
        if self._sessions is None:
            from hai_agents_local.sessions import LocalSessionsClient

            self._sessions = LocalSessionsClient(
                client_wrapper=self._client_wrapper, hold=self._hold, auto_bridges=self._auto_bridges
            )
        return self._sessions


class AsyncClient(_LocalRuntimeAccess, AsyncBaseClient):
    __init__ = _default_api_key(AsyncBaseClient.__init__)

    @classmethod
    async def local(
        cls,
        *,
        runtime: typing.Optional[LocalRuntime] = None,
        inference: typing.Optional[Inference] = None,
        local_options: typing.Optional[typing.Dict[str, typing.Any]] = None,
        auto_bridges: bool = True,
        timeout: typing.Optional[float] = None,
    ) -> AsyncClient:
        """A client on a local agent runtime: ``runtime`` if given, else one this client starts and owns."""
        from hai_agents_local.runtime.acquire import RuntimeHold

        hold = await RuntimeHold.acquire_async(runtime, inference=inference, local_options=local_options)
        try:
            client = cls(
                base_url=hold.runtime.base_url, api_key=hold.api_key, httpx_client=hold.async_http_client(timeout)
            )
        except BaseException:
            if hold.owned:
                await asyncio.to_thread(hold.runtime.shutdown)
            raise
        client._hold, client._auto_bridges = hold, auto_bridges
        return client

    async def aclose(self) -> None:
        """Stop sessions this client bridged; a local client also stops its runtime once no other client uses it."""
        try:
            if self._sessions is not None:
                await self._sessions.aclose()
        finally:
            if self.local_runtime is not None:
                try:
                    if self._owns_runtime:
                        await asyncio.to_thread(
                            self.local_runtime.shutdown_if_idle, getattr(self._sessions, "own_session_ids", ())
                        )
                finally:
                    await self._client_wrapper.httpx_client.httpx_client.aclose()

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc: typing.Any) -> None:
        await self.aclose()

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
    def sessions(self) -> AsyncSessionsClient:
        if self._sessions is None:
            from hai_agents_local.sessions import LocalAsyncSessionsClient

            self._sessions = LocalAsyncSessionsClient(
                client_wrapper=self._client_wrapper, hold=self._hold, auto_bridges=self._auto_bridges
            )
        return self._sessions

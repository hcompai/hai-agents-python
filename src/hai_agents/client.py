"""Client classes extended with create-and-run convenience methods.

Fern emits the API surface as ``BaseClient``/``AsyncBaseClient``; these thin
subclasses add the object-oriented sugar (``run_session``, ``start_session``,
``session``) that delegates to the hand-written polling helpers.
"""

from __future__ import annotations

import asyncio
import contextlib
import typing

import typing_extensions

from .base_client import AsyncBaseClient, BaseClient
from .inference import Inference
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


class Client(BaseClient):
    def __init__(
        self,
        *,
        mode: typing.Literal["local", "remote"] = "remote",
        inference: typing.Optional[Inference] = None,
        auto_bridges: bool = True,
        runtime: typing.Any = None,
        local_options: typing.Optional[typing.Dict[str, typing.Any]] = None,
        **kwargs: typing.Any,
    ) -> None:
        if mode not in {"local", "remote"}:
            raise ValueError("mode must be local or remote")
        self._auto_bridges = auto_bridges
        self.mode = mode
        self.local_runtime = None
        self._owns_runtime = mode == "local" and runtime is None
        self._owns_http = kwargs.get("httpx_client") is None
        if mode == "remote":
            if runtime is not None or local_options is not None:
                raise ValueError("runtime and local_options require mode='local'")
            if inference is not None and inference.base_url is not None:
                raise ValueError("self-hosted inference currently requires a local agent")
        else:
            if "base_url" in kwargs or "api_key" in kwargs:
                raise ValueError(
                    "local API credentials come from runtime; pass inference credentials via local_options"
                )
            if runtime is not None and (local_options is not None or inference is not None):
                raise ValueError("an attached runtime owns its inference and launch configuration")
            if runtime is None:
                from .local.runtime import LocalRuntime

                options = dict(local_options or {})
                options["required_recipe"] = "shared"
                options["spawn_env"] = {"HAI_AGENT_RUNTIME_RECIPE": "shared", **options.get("spawn_env", {})}
                if inference is not None:
                    options["spawn_env"] = inference.runtime_env(options.get("spawn_env"))
                    options["inherit_env"] = False
                runtime = LocalRuntime.ensure_started(**options)
            if inference is not None and not runtime.owned:
                raise ValueError("inference selection cannot reconfigure an existing runtime; choose a free local port")
            runtime.require_recipe("shared")
            self.local_runtime = runtime
            kwargs.update(base_url=runtime.base_url, api_key=runtime.api_key)
        try:
            super().__init__(**kwargs)
        except BaseException:
            if self._owns_runtime and self.local_runtime is not None and self.local_runtime.owned:
                self.local_runtime.shutdown()
            raise

    def close(self) -> None:
        """Release this client's connections and any runtime it started; borrowed runtimes stay alive."""
        try:
            if self._sessions is not None and hasattr(self._sessions, "close"):
                self._sessions.close()
        finally:
            try:
                if self._owns_runtime and self.local_runtime is not None and self.local_runtime.owned:
                    self.local_runtime.shutdown()
            finally:
                if self._owns_http:
                    self._client_wrapper.httpx_client.httpx_client.close()

    def __enter__(self) -> "Client":
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
        if not self._auto_bridges:
            return super().sessions
        if self._sessions is None:
            from hai_agents_local.sessions import LocalSessionsClient

            self._sessions = LocalSessionsClient(client_wrapper=self._client_wrapper)
        return self._sessions


class AsyncClient(AsyncBaseClient):
    def __init__(
        self,
        *,
        mode: typing.Literal["local", "remote"] = "remote",
        inference: typing.Optional[Inference] = None,
        auto_bridges: bool = True,
        runtime: typing.Any = None,
        local_options: typing.Optional[typing.Dict[str, typing.Any]] = None,
        **kwargs: typing.Any,
    ) -> None:
        if mode not in {"local", "remote"}:
            raise ValueError("mode must be local or remote")
        self._auto_bridges = auto_bridges
        self.mode = mode
        self.local_runtime = None
        self._owns_runtime = mode == "local" and runtime is None
        self._owns_http = kwargs.get("httpx_client") is None
        if mode == "remote":
            if runtime is not None or local_options is not None:
                raise ValueError("runtime and local_options require mode='local'")
            if inference is not None and inference.base_url is not None:
                raise ValueError("self-hosted inference currently requires a local agent")
        else:
            if "base_url" in kwargs or "api_key" in kwargs:
                raise ValueError(
                    "local API credentials come from runtime; pass inference credentials via local_options"
                )
            if runtime is not None and (local_options is not None or inference is not None):
                raise ValueError("an attached runtime owns its inference and launch configuration")
            if runtime is None:
                raise ValueError("Use await AsyncClient.local() to start a runtime without blocking the event loop")
            if inference is not None and not runtime.owned:
                raise ValueError("inference selection cannot reconfigure an existing runtime; choose a free local port")
            runtime.require_recipe("shared")
            self.local_runtime = runtime
            kwargs.update(base_url=runtime.base_url, api_key=runtime.api_key)
        try:
            super().__init__(**kwargs)
        except BaseException:
            if self._owns_runtime and self.local_runtime is not None and self.local_runtime.owned:
                self.local_runtime.shutdown()
            raise

    @classmethod
    async def local(
        cls,
        *,
        inference: typing.Optional[Inference] = None,
        local_options: typing.Optional[typing.Dict[str, typing.Any]] = None,
        **kwargs: typing.Any,
    ) -> "AsyncClient":
        """Start or attach off the event loop; the returned client owns any runtime it starts."""
        from .local.runtime import LocalRuntime

        options = dict(local_options or {})
        options["required_recipe"] = "shared"
        options["spawn_env"] = {"HAI_AGENT_RUNTIME_RECIPE": "shared", **options.get("spawn_env", {})}
        if inference is not None:
            options["spawn_env"] = inference.runtime_env(options.get("spawn_env"))
            options["inherit_env"] = False
        runtime = await LocalRuntime.ensure_started_async(**options)
        construction = None
        try:
            if inference is not None and not runtime.owned:
                raise ValueError("inference selection cannot reconfigure an existing runtime; choose a free local port")
            construction = asyncio.create_task(asyncio.to_thread(cls, mode="local", runtime=runtime, **kwargs))
            client = await asyncio.shield(construction)
            client._owns_runtime = True
            return client
        except BaseException:
            if construction is not None:
                with contextlib.suppress(Exception):
                    client = await construction
                    await client.aclose()
            if runtime.owned:
                await asyncio.to_thread(runtime.shutdown)
            raise

    async def aclose(self) -> None:
        """Release this client's connections and any runtime it started; borrowed runtimes stay alive."""
        try:
            if self._sessions is not None and hasattr(self._sessions, "aclose"):
                await self._sessions.aclose()
        finally:
            try:
                if self._owns_runtime and self.local_runtime is not None and self.local_runtime.owned:
                    await asyncio.to_thread(self.local_runtime.shutdown)
            finally:
                if self._owns_http:
                    await self._client_wrapper.httpx_client.httpx_client.aclose()

    async def __aenter__(self) -> "AsyncClient":
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
        if not self._auto_bridges:
            return super().sessions
        if self._sessions is None:
            from hai_agents_local.sessions import LocalAsyncSessionsClient

            self._sessions = LocalAsyncSessionsClient(client_wrapper=self._client_wrapper)
        return self._sessions

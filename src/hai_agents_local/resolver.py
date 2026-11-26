"""This machine's MCP servers, each at `/mcp/<name>` on loopback, for `mcporter` in the agent's confined shell.

The servers' keys and commands stay in this process: the shell holds only the bridge's token, which reaches this
server alone and dies with the bridge.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import logging
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from typing import Any

from .connections import Connection, connections_path

logger = logging.getLogger(__name__)

START_S = 10.0
# A whole stop, inside the bridge manager's join of the bridge that runs this resolver.
STOP_S = 2.0
CONNECT_S = 30.0
# Above mcporter's own timeout, which the bridge sets to `MCPORTER_CALL_TIMEOUT_MS`: mcporter gives up first.
CALL_S = 210.0
MCPORTER_CALL_TIMEOUT_MS = 200_000
STDERR_CHARACTERS = 600
REFUSED = -32000
CLOSED = "the connection to the server closed"
_Transport = Callable[[], AbstractAsyncContextManager[Any]]


class Resolver:
    """Serves `connections` on 127.0.0.1 from a thread of its own, to requests that carry `token`."""

    def __init__(self, connections: Sequence[Connection]) -> None:
        self.connections = {connection.name: connection for connection in connections}
        self.token = secrets.token_urlsafe(32)
        self.port: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stopping: asyncio.Event | None = None
        self._started = threading.Event()
        self._failure: BaseException | None = None
        self._upstreams: dict[str, _Upstream] = {}
        self._tools: dict[str, list[Any]] = {}
        self._opening: dict[str, asyncio.Lock] = {}

    @property
    def host(self) -> str:
        """`127.0.0.1:<port>`, the one address the sandbox lets the shell reach for it."""
        if self.port is None:
            raise RuntimeError("the MCP resolver is not serving")
        return f"127.0.0.1:{self.port}"

    def url(self, name: str) -> str:
        return f"http://{self.host}/mcp/{name}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="hai-mcp-resolver", daemon=True)
        self._thread.start()
        if not self._started.wait(START_S) or self._failure is not None:
            self.stop()
            raise RuntimeError(f"the MCP resolver did not start: {self._failure}")
        logger.info("MCP servers %s served at %s", ", ".join(self.connections), self.host)

    def stop(self) -> None:
        if self._loop is not None and self._stopping is not None:
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._stopping.set)
        if self._thread is not None:
            self._thread.join(STOP_S + 1)
        self._thread, self.port = None, None

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as error:  # noqa: BLE001 - told to the thread that waits on start
            self._failure = error
            self._started.set()

    async def _serve(self) -> None:
        self._loop, self._stopping = asyncio.get_running_loop(), asyncio.Event()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        import uvicorn

        server = uvicorn.Server(uvicorn.Config(self._app(), log_level="warning", lifespan="on", access_log=False))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            while not server.started:
                if serving.done():
                    await serving
                    raise RuntimeError("it stopped as it started")
                await asyncio.sleep(0.02)
            self.port = listener.getsockname()[1]
            self._started.set()
            await self._stopping.wait()
        finally:
            # Forced: a connected `mcporter` holds its stream open, which a graceful stop waits out.
            server.should_exit = server.force_exit = True
            closing = asyncio.gather(
                serving, *(upstream.close() for upstream in self._upstreams.values()), return_exceptions=True
            )
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(closing, STOP_S)

    def _app(self) -> Any:
        from mcp import types
        from mcp.server.lowlevel import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Mount

        server: Server[Any, Any] = Server("hai-connections")

        async def list_tools(_: types.ListToolsRequest) -> types.ServerResult:
            name = self._addressed(server)
            await self._reach(name)
            tools = [tool.model_copy(update={"outputSchema": None}) for tool in self._tools[name]]
            return types.ServerResult(types.ListToolsResult(tools=tools))

        async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
            name = self._addressed(server)
            return types.ServerResult(await self._call(name, request.params.name, request.params.arguments or {}))

        # Registered by hand: the decorators cache tool definitions by name alone, across every server here.
        server.request_handlers[types.ListToolsRequest] = list_tools
        server.request_handlers[types.CallToolRequest] = call_tool
        manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True)

        async def endpoint(scope: Any, receive: Any, send: Any) -> None:
            headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
            scheme, _, token = headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not secrets.compare_digest(token.strip(), self.token):
                refused = "this request carries no live token: reach MCP servers with `mcporter`, which sends it"
                await JSONResponse({"error": refused}, status_code=401)(scope, receive, send)
                return
            await manager.handle_request(scope, receive, send)

        @asynccontextmanager
        async def lifespan(_: Any) -> AsyncIterator[None]:
            async with manager.run():
                yield

        return Starlette(routes=[Mount("/mcp", app=endpoint)], lifespan=lifespan)

    def _addressed(self, server: Any) -> str:
        from mcp.shared.exceptions import McpError
        from mcp.types import ErrorData

        request = server.request_context.request
        name = request.url.path.rstrip("/").rsplit("/", 1)[-1] if request is not None else ""
        if name not in self.connections:
            served = ", ".join(self.connections) or "none"
            raise McpError(ErrorData(code=REFUSED, message=f"no MCP server named {name!r} here; served: {served}"))
        return name

    async def _reach(self, name: str) -> _Upstream:
        from mcp.shared.exceptions import McpError
        from mcp.types import ErrorData

        async with self._opening.setdefault(name, asyncio.Lock()):
            upstream = self._upstreams.get(name)
            if upstream is not None and upstream.alive:
                return upstream
            if upstream is not None:
                await upstream.close()
            try:
                upstream = _Upstream(_transport(self.connections[name]))
                self._tools[name] = await upstream.open()
            except Exception as error:  # noqa: BLE001 - an unreachable server is told to the agent
                logger.warning("MCP server %s did not connect: %s", name, _cause(error))
                raise McpError(
                    ErrorData(code=REFUSED, message=f"{name} could not be reached: {_cause(error)}")
                ) from error
            self._upstreams[name] = upstream
            return upstream

    async def _call(self, name: str, tool: str, arguments: dict[str, Any]) -> Any:
        from mcp import types

        upstream = await self._reach(name)
        try:
            return await upstream.call(tool, arguments)
        except Exception as error:  # noqa: BLE001 - the server's failure is the call's answer
            logger.warning("MCP call %s.%s failed: %s", name, tool, type(error).__name__)
            note = f"{name} could not run {tool}: {_cause(error)}"
            return types.CallToolResult(content=[types.TextContent(type="text", text=note)], isError=True)


def check(connections: Sequence[Connection]) -> dict[str, list[str] | BaseException]:
    """Each server's tool names, or why it did not connect."""

    async def tools(connection: Connection) -> list[str]:
        upstream: _Upstream | None = None
        try:
            upstream = _Upstream(_transport(connection))
            return [tool.name for tool in await upstream.open()]
        finally:
            if upstream is not None:
                await upstream.close()

    async def every() -> list[list[str] | BaseException]:
        return await asyncio.gather(*map(tools, connections), return_exceptions=True)

    found = asyncio.run(every())
    return {
        connection.name: _cause(result) if isinstance(result, BaseException) else result
        for connection, result in zip(connections, found)
    }


class _Upstream:
    """One server's session, entered and left by one task: anyio refuses to unwind a transport in another task."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport
        self._ready: asyncio.Future[tuple[Any, list[Any]]] = asyncio.get_running_loop().create_future()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def alive(self) -> bool:
        return self._task is not None and not self._task.done() and not self._stop.is_set()

    async def open(self) -> list[Any]:
        self._task = asyncio.create_task(self._serve())
        try:
            _, tools = await asyncio.wait_for(asyncio.shield(self._ready), CONNECT_S)
        except BaseException:
            await self.close()
            raise
        return tools

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        from mcp.shared.exceptions import McpError
        from mcp.types import CONNECTION_CLOSED

        if not self.alive:
            raise ConnectionError(CLOSED)
        session, _ = self._ready.result()
        try:
            return await session.call_tool(tool, arguments, read_timeout_seconds=timedelta(seconds=CALL_S))
        except McpError as error:
            if error.error.code == CONNECTION_CLOSED:
                self._stop.set()
            raise

    async def close(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, CONNECT_S)
        except (TimeoutError, asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        except Exception:  # noqa: BLE001 - a failed connection was told to whoever opened it
            pass
        finally:
            self._task = None

    async def _serve(self) -> None:
        from mcp import ClientSession

        try:
            async with self._transport() as streams, ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listed = await session.list_tools()
                self._ready.set_result((session, listed.tools))
                await self._stop.wait()
        except Exception as error:  # noqa: BLE001 - the failure belongs to whoever opened the connection
            if not self._ready.done():
                self._ready.set_exception(error)
        finally:
            if not self._ready.done():
                self._ready.set_exception(ConnectionError(CLOSED))


def _transport(connection: Connection) -> _Transport:
    if connection.transport == "stdio":
        return _stdio(connection)
    url, headers = connection.url, dict(connection.headers)

    @asynccontextmanager
    async def open_transport() -> AsyncIterator[Any]:
        if connection.transport == "sse":
            from mcp.client.sse import sse_client

            async with sse_client(url, headers=headers, timeout=CONNECT_S, sse_read_timeout=CALL_S) as streams:
                yield streams
            return
        import httpx
        from mcp.client.streamable_http import streamable_http_client

        timeout = httpx.Timeout(CALL_S, connect=CONNECT_S)
        async with (
            httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False) as client,
            streamable_http_client(url, http_client=client) as streams,
        ):
            yield streams

    return open_transport


def _stdio(connection: Connection) -> _Transport:
    """The command is a child of this process, outside the sandbox, as the user's MCP clients run it."""
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    executable = shutil.which(connection.command)
    if executable is None:
        raise ValueError(f"{connection.name} runs `{connection.command}`, which is not installed on this machine")
    keep = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "USER", "LOGNAME", "SystemRoot", "USERPROFILE")
    host = {name: os.environ[name] for name in keep if name in os.environ}
    parameters = StdioServerParameters(
        command=executable, args=list(connection.args), env={**host, **connection.env}, cwd=connection.cwd
    )

    @asynccontextmanager
    async def open_transport() -> AsyncIterator[Any]:
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as printed:
            try:
                async with stdio_client(parameters, errlog=printed) as streams:
                    yield streams
            except Exception as error:
                printed.seek(0)
                if said := printed.read()[-STDERR_CHARACTERS:].strip():
                    logger.warning("%s stderr: %s", connection.name, said)
                raise ConnectionError(str(_cause(error))) from error

    return open_transport


def _cause(error: BaseException) -> BaseException:
    """The first leaf of an exception group: anyio wraps a transport's failure in one."""
    while getattr(error, "exceptions", None):
        error = error.exceptions[0]  # type: ignore[attr-defined]
    return error

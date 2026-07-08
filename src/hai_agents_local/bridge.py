from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any, AsyncIterator, ClassVar, Generic, TypeVar, Union

import httpx

from .config import default_base_url
from .errors import RateLimitedError, SessionNotFoundError
from .transport import Command, CommandExchange, Json, deserialize_args, serialize_result

logger = logging.getLogger(__name__)

TokenSource = Union[str, Callable[[], str], Callable[[], Awaitable[str]]]

LONG_POLL_SECONDS = 20
LONG_POLL_READ_TIMEOUT_S = 21.0
MIN_POLL_INTERVAL_S = 1.0
POST_RESULT_TIMEOUT_S = 10.0
POST_RESULT_RETRIES = 2
FETCH_TRANSIENT_RETRIES = 2
MAX_RECONNECT_DELAY_S = 60.0
MIN_RATE_LIMIT_BACKOFF_S = 1.0
RESULT_CACHE_SIZE = 512

DriverT = TypeVar("DriverT")


class _BearerAuth(httpx.Auth):
    """Resolves the bearer token per request, so rotating or async token sources stay current."""

    def __init__(self, source: TokenSource) -> None:
        self._source = source

    async def async_auth_flow(self, request: httpx.Request) -> AsyncIterator[httpx.Response]:
        token = self._source() if callable(self._source) else self._source
        if inspect.isawaitable(token):
            token = await token
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


class LocalBridge(ABC, Generic[DriverT]):
    """Polls the command channel for session_id and dispatches each command to a local hai-drivers driver."""

    environment_kind: ClassVar[str]

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.environment_id = environment_id or self.environment_kind
        self.api_key = api_key
        self.base_url = base_url or default_base_url()
        self.session_id = session_id or str(uuid.uuid4())
        self.ready = threading.Event()
        self.on_crash: Callable[[], None] | None = None
        self._driver: DriverT | None = None
        self._stop_event = asyncio.Event()
        self._results: OrderedDict[str, tuple[Json, str | None]] = OrderedDict()

    @abstractmethod
    def create_driver(self) -> DriverT:
        """Build the hai-drivers driver this bridge dispatches commands to."""

    @abstractmethod
    def driver_interface(self) -> type:
        """The hai-drivers interface ABC whose public methods define the accepted commands."""

    @functools.cached_property
    def commands(self) -> frozenset[str]:
        return frozenset(name for name in dir(self.driver_interface()) if not name.startswith("_"))

    def request_stop(self) -> None:
        """Signal the poll loop to stop; safe to call from a signal handler."""
        self._stop_event.set()

    async def run(self) -> None:
        """Serve commands until stopped; raises AuthError on a bad key."""
        self._stop_event.clear()
        try:
            async with httpx.AsyncClient(
                headers={"Accept": "application/json"}, auth=_BearerAuth(self.api_key), follow_redirects=True
            ) as client:
                exchange = CommandExchange(client, self.base_url)
                await exchange.ensure_channel(self.session_id)
                if self._driver is None:
                    self._driver = await asyncio.to_thread(self.create_driver)
                self.ready.set()
                await self._poll_loop(exchange)
        finally:
            destroy = getattr(self._driver, "destroy", None)
            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    logger.warning("driver teardown failed", exc_info=True)

    async def _poll_loop(self, exchange: CommandExchange) -> None:
        retry_delay = 1.0
        while not self._stop_event.is_set():
            try:
                started = time.monotonic()
                commands = await self._fetch_until_stop(exchange)
                retry_delay = 1.0
                if commands:
                    await self._process_commands(exchange, commands)
                elif time.monotonic() - started < MIN_POLL_INTERVAL_S and await self._interruptible_sleep(
                    MIN_POLL_INTERVAL_S
                ):
                    # Instant empty polls are paced so a misbehaving server cannot cause a busy loop.
                    break
            except SessionNotFoundError:
                # Channel was garbage-collected server-side; recreate and resume.
                logger.warning("channel %s missing; recreating", self.session_id)
                await exchange.ensure_channel(self.session_id)
                if await self._interruptible_sleep(retry_delay):
                    break
                retry_delay = min(retry_delay * 2, MAX_RECONNECT_DELAY_S)
            except RateLimitedError as exc:
                backoff = max(exc.retry_after, MIN_RATE_LIMIT_BACKOFF_S)
                logger.warning("rate limited; backing off %.0fs", backoff)
                if await self._interruptible_sleep(backoff):
                    break
            except httpx.HTTPError as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    # A 4xx will not heal by waiting; surface it instead of retrying forever.
                    raise
                # Network blips and 5xx: exponential backoff, keep serving when the platform returns.
                logger.warning("connection error: %s; retrying in %.0fs", exc, retry_delay)
                if await self._interruptible_sleep(retry_delay):
                    break
                retry_delay = min(retry_delay * 2, MAX_RECONNECT_DELAY_S)

    async def _fetch_until_stop(self, exchange: CommandExchange) -> list[Command] | None:
        """Long-poll for commands, returning early (with None) when a stop is requested."""
        fetch_task = asyncio.ensure_future(
            exchange.fetch_commands(
                self.session_id,
                wait_for_seconds=LONG_POLL_SECONDS,
                read_timeout=LONG_POLL_READ_TIMEOUT_S,
                max_retries=FETCH_TRANSIENT_RETRIES,
            )
        )
        stop_task = asyncio.ensure_future(self._stop_event.wait())
        try:
            done, _ = await asyncio.wait({fetch_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not stop_task.done():
                stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_task
        if stop_task in done and not fetch_task.done():
            fetch_task.cancel()
            try:
                await fetch_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("in-flight fetch failed during stop: %s", exc)
            return None
        return fetch_task.result()

    async def _process_commands(self, exchange: CommandExchange, commands: list[Command]) -> None:
        for cmd in commands:
            if self._stop_event.is_set():
                break
            if cmd.command_uid in self._results:
                # Redelivered command: repost the cached result instead of re-executing.
                self._results.move_to_end(cmd.command_uid)
                result, error = self._results[cmd.command_uid]
            else:
                result, error = await asyncio.to_thread(self._dispatch, cmd.name, cmd.args)
                self._results[cmd.command_uid] = (result, error)
                while len(self._results) > RESULT_CACHE_SIZE:
                    self._results.popitem(last=False)
            await self._deliver(exchange, cmd.id, cmd.command_uid, result, error)

    def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[Json, str | None]:
        if name not in self.commands:
            return None, f"command {name!r} is not supported by this {self.environment_kind} bridge"
        attr = getattr(self._driver, name)
        started = time.monotonic()
        try:
            result = self._call_driver_method(attr, deserialize_args(name, args)) if callable(attr) else attr
            logger.info("command %s dispatched in %.2fs", name, time.monotonic() - started)
            return serialize_result(result), None
        except NotImplementedError:
            return None, f"command {name!r} is not supported by this driver"
        except Exception as exc:
            logger.warning("command %s raised: %s", name, exc)
            return None, str(exc)

    @staticmethod
    def _call_driver_method(method: Callable[..., Any], args: dict[str, Any]) -> Any:
        """Call with wire kwargs, splatting a list bound to a var-positional param (execute_script's args)."""
        try:
            params = list(inspect.signature(method).parameters.values())
        except (TypeError, ValueError):
            return method(**args)
        star_idx = next((i for i, p in enumerate(params) if p.kind is inspect.Parameter.VAR_POSITIONAL), None)
        if star_idx is None or params[star_idx].name not in args:
            return method(**args)
        kwargs = dict(args)
        leading = [kwargs.pop(p.name) for p in params[:star_idx] if p.name in kwargs]
        variadic = kwargs.pop(params[star_idx].name)
        return method(*leading, *variadic, **kwargs)

    async def _deliver(
        self, exchange: CommandExchange, command_id: str, command_uid: str, result: Json, error: str | None
    ) -> None:
        """Post the result, retrying transient failures; raises when delivery keeps failing so the poll
        loop backs off and the redelivered command reposts from the result cache."""
        for attempt in range(POST_RESULT_RETRIES + 1):
            try:
                await exchange.post_result(
                    command_id, command_uid=command_uid, result=result, error=error, timeout=POST_RESULT_TIMEOUT_S
                )
                return
            except httpx.HTTPError as exc:
                if attempt == POST_RESULT_RETRIES:
                    raise
                logger.warning("post result for %s failed (attempt %d): %s", command_id, attempt + 1, exc)
            await asyncio.sleep(0.5 * (attempt + 1))

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; True when woken by a stop request."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except (TimeoutError, asyncio.TimeoutError):
            return False
        return True

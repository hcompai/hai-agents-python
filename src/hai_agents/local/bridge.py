from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, ClassVar, Generic, TypeVar

import httpx

from .config import API_KEY_ENV_VAR, LocalSettings
from .errors import AuthError, BridgeBusyError, RateLimitedError, SessionNotFoundError
from .lease import MachineLease
from .transport import CommandExchange, Json, deserialize_args, serialize_result
from .utils import session_id_from_environment_id

logger = logging.getLogger(__name__)

LONG_POLL_SECONDS = 20
LONG_POLL_READ_TIMEOUT_S = 21.0
MIN_POLL_INTERVAL_S = 1.0
POST_RESULT_TIMEOUT_S = 10.0
POST_RESULT_RETRIES = 2
FETCH_TRANSIENT_RETRIES = 2
MAX_RECONNECT_DELAY_S = 60.0
MIN_RATE_LIMIT_BACKOFF_S = 1.0
RESULT_CACHE_SIZE = 512
LEASE_GRACE_S = 10.0
LEASE_RETRY_S = 0.5

DriverT = TypeVar("DriverT")


class LocalBridge(ABC, Generic[DriverT]):
    """Serves one environment kind on this machine: polls the platform's
    command channel for ``session_id`` and dispatches each command to a local
    hai-drivers driver (see ``transport`` for the wire protocol)."""

    environment_kind: ClassVar[str]

    def __init__(
        self,
        environment_id: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        session_id: str | None = None,
    ) -> None:
        settings = LocalSettings.from_env()
        resolved_key = api_key or settings.api_key
        if not resolved_key:
            raise ValueError(f"api_key is required (pass api_key= or set {API_KEY_ENV_VAR})")
        self.environment_id = environment_id
        self.api_key = resolved_key
        self.base_url = base_url or settings.base_url
        self.session_id = session_id or session_id_from_environment_id(
            environment_id, self.api_key, self.environment_kind
        )
        self.ready = threading.Event()
        self._driver: DriverT | None = None
        self._lease = MachineLease(self.environment_kind, self.session_id)
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
        """Serve commands until stopped; raises AuthError or BridgeBusyError when it cannot start."""
        await self._acquire_lease()
        self._stop_event.clear()
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
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
            self._lease.release()

    async def _acquire_lease(self) -> None:
        """A stopping bridge may hold the kind lease until its in-flight command finishes,
        so retry briefly before declaring a conflict with another environment."""
        deadline = time.monotonic() + LEASE_GRACE_S
        while True:
            try:
                self._lease.acquire()
                return
            except BridgeBusyError:
                raise
            except RuntimeError:
                if time.monotonic() >= deadline or await self._interruptible_sleep(LEASE_RETRY_S):
                    raise

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
                    # An empty poll that returned instantly: pace requests so a
                    # misbehaving server cannot turn long-polling into a busy loop.
                    break
            except AuthError as exc:
                # Not recoverable by waiting: a bad key stays bad.
                logger.error("auth error, stopping: %s", exc)
                break
            except SessionNotFoundError:
                # The channel was garbage-collected server-side; recreate and resume.
                logger.warning("channel %s missing; recreating", self.session_id)
                try:
                    await exchange.ensure_channel(self.session_id)
                except AuthError as exc:
                    logger.error("auth error recreating channel, stopping: %s", exc)
                    break
                if await self._interruptible_sleep(retry_delay):
                    break
                retry_delay = min(retry_delay * 2, MAX_RECONNECT_DELAY_S)
            except RateLimitedError as exc:
                backoff = max(exc.retry_after, MIN_RATE_LIMIT_BACKOFF_S)
                logger.warning("rate limited; backing off %.0fs", backoff)
                if await self._interruptible_sleep(backoff):
                    break
            except httpx.HTTPError as exc:
                # Network blips: exponential backoff, keep serving when connectivity returns.
                logger.warning("connection error: %s; retrying in %.0fs", exc, retry_delay)
                if await self._interruptible_sleep(retry_delay):
                    break
                retry_delay = min(retry_delay * 2, MAX_RECONNECT_DELAY_S)

    async def _fetch_until_stop(self, exchange: CommandExchange) -> list[dict[str, Any]] | None:
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

    async def _process_commands(self, exchange: CommandExchange, commands: list[dict[str, Any]]) -> None:
        for cmd in commands:
            if self._stop_event.is_set():
                break
            cmd_id, cmd_uid = cmd.get("id"), cmd.get("command_uid")
            if cmd_id is None or cmd_uid is None:
                logger.warning("skipping command with missing id/command_uid: %s", cmd)
                continue
            cmd_uid = str(cmd_uid)
            if cmd_uid in self._results:
                # Redelivered command: repost the cached result instead of re-executing,
                # so retries after a lost response stay idempotent.
                self._results.move_to_end(cmd_uid)
                result, error = self._results[cmd_uid]
            else:
                result, error = await asyncio.to_thread(self._dispatch, cmd.get("name", ""), cmd.get("args") or {})
                self._results[cmd_uid] = (result, error)
                while len(self._results) > RESULT_CACHE_SIZE:
                    self._results.popitem(last=False)
            await self._deliver(exchange, str(cmd_id), cmd_uid, result, error)

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
        """Invoke a driver method with wire args, splatting a var-positional tuple bound
        under its parameter name: ``execute_script(script, *args, n_unsafe_attempts=2)``
        arrives as ``{"script": "...", "args": [1, "two"], "n_unsafe_attempts": 3}`` and
        must be called as ``execute_script("...", 1, "two", n_unsafe_attempts=3)``."""
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
        for attempt in range(POST_RESULT_RETRIES + 1):
            try:
                if await exchange.post_result(
                    command_id, command_uid=command_uid, result=result, error=error, timeout=POST_RESULT_TIMEOUT_S
                ):
                    return
            except httpx.HTTPError as exc:
                logger.warning("post result for %s failed (attempt %d): %s", command_id, attempt + 1, exc)
            if attempt < POST_RESULT_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))
        logger.error("failed to deliver result for command %s", command_id)

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; True when woken by a stop request."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except (TimeoutError, asyncio.TimeoutError):
            return False
        return True

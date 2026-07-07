from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, ClassVar

import httpx

from ..environment import HaiAgentsEnvironment
from .transport import (
    AuthError,
    CommandExchange,
    RateLimitedError,
    SessionNotFoundError,
    deserialize_args,
    serialize_result,
)

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "HAI_API_KEY"
BASE_URL_ENV_VAR = "HAI_API_BASE_URL"
DEFAULT_BASE_URL = HaiAgentsEnvironment.EU.value
LEASE_DIR = Path.home() / ".hai"

LONG_POLL_SECONDS = 20
LONG_POLL_READ_TIMEOUT_S = 21.0
MIN_POLL_INTERVAL_S = 1.0
POST_RESULT_TIMEOUT_S = 10.0
POST_RESULT_RETRIES = 2
FETCH_TRANSIENT_RETRIES = 2
MAX_RECONNECT_DELAY_S = 60.0
MIN_RATE_LIMIT_BACKOFF_S = 1.0
RESULT_CACHE_SIZE = 512


def session_id_from_environment_id(environment_id: str, api_key: str, environment_kind: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{api_key}.{environment_id}.{environment_kind}"))


class BridgeBusyError(RuntimeError):
    pass


class _MachineLease:
    """One lock file per environment kind, holding the owner's session_id, so the
    one-bridge-per-kind rule applies across processes."""

    def __init__(self, environment_kind: str, session_id: str) -> None:
        self._environment_kind = environment_kind
        self._session_id = session_id
        self._path = LEASE_DIR / f"bridge-{environment_kind}.lock"
        self._handle: Any = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+")
        try:
            self._lock(handle)
        except OSError as exc:
            handle.close()
            if self._read_holder() == self._session_id:
                raise BridgeBusyError(f"another bridge already serves session {self._session_id}") from exc
            raise RuntimeError(
                f"another process already serves a local {self._environment_kind} environment on this machine"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(self._session_id)
        handle.flush()
        self._handle = handle

    def _read_holder(self) -> str | None:
        try:
            return self._path.read_text().strip()
        except OSError:
            return None

    def release(self) -> None:
        if self._handle is not None:
            try:
                self._handle.seek(0)
                self._handle.truncate()
                self._handle.flush()
                self._unlock(self._handle)
            finally:
                self._handle.close()
                self._handle = None

    @staticmethod
    def _lock(handle: Any) -> None:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    @staticmethod
    def _unlock(handle: Any) -> None:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _call(method: Callable[..., Any], args: dict[str, Any]) -> Any:
    """Invoke method with proxy-serialized args, splatting a var-positional tuple bound under its param name."""
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


class LocalBridge(ABC):
    """Serves one environment kind on this machine: polls the platform's
    command channel for ``session_id`` and dispatches each command to a local
    hai-drivers driver."""

    environment_kind: ClassVar[str]

    def __init__(
        self,
        environment_id: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.environment_id = environment_id
        self.api_key = api_key or os.getenv(API_KEY_ENV_VAR) or ""
        if not self.api_key:
            raise ValueError(f"api_key is required (pass api_key= or set {API_KEY_ENV_VAR})")
        self.base_url = base_url or os.getenv(BASE_URL_ENV_VAR) or DEFAULT_BASE_URL
        self.session_id = session_id or session_id_from_environment_id(
            environment_id, self.api_key, self.environment_kind
        )
        self.ready = threading.Event()
        self._driver: Any = None
        self._lease = _MachineLease(self.environment_kind, self.session_id)
        self._stop_event = asyncio.Event()
        self._results: OrderedDict[str, tuple[Any, str | None]] = OrderedDict()

    @abstractmethod
    def create_driver(self) -> Any:
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
        self._lease.acquire()
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
                    break
            except AuthError as exc:
                logger.error("auth error, stopping: %s", exc)
                break
            except SessionNotFoundError:
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
                logger.warning("connection error: %s; retrying in %.0fs", exc, retry_delay)
                if await self._interruptible_sleep(retry_delay):
                    break
                retry_delay = min(retry_delay * 2, MAX_RECONNECT_DELAY_S)

    async def _fetch_until_stop(self, exchange: CommandExchange) -> list[dict[str, Any]] | None:
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
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await fetch_task
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
                self._results.move_to_end(cmd_uid)
                result, error = self._results[cmd_uid]
            else:
                result, error = await asyncio.to_thread(self._dispatch, cmd.get("name", ""), cmd.get("args") or {})
                self._results[cmd_uid] = (result, error)
                while len(self._results) > RESULT_CACHE_SIZE:
                    self._results.popitem(last=False)
            await self._deliver(exchange, str(cmd_id), cmd_uid, result, error)

    def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[Any, str | None]:
        if name not in self.commands:
            return None, f"command {name!r} is not supported by this {self.environment_kind} bridge"
        attr = getattr(self._driver, name)
        started = time.monotonic()
        try:
            result = _call(attr, deserialize_args(name, args)) if callable(attr) else attr
            logger.info("command %s dispatched in %.2fs", name, time.monotonic() - started)
            return serialize_result(result), None
        except NotImplementedError:
            return None, f"command {name!r} is not supported by this driver"
        except Exception as exc:
            logger.warning("command %s raised: %s", name, exc)
            return None, str(exc)

    async def _deliver(
        self, exchange: CommandExchange, command_id: str, command_uid: str, result: Any, error: str | None
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
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except (TimeoutError, asyncio.TimeoutError):
            return False
        return True

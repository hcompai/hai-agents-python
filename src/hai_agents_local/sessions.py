"""Sessions clients that auto-start local bridges for user_device environments."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import functools
import inspect
import json
import logging
import threading
import typing

import httpx

from hai_agents.base_client import BaseClient
from hai_agents.core.api_error import ApiError
from hai_agents.core.request_options import RequestOptions
from hai_agents.sessions.client import AsyncSessionsClient, SessionsClient

from .bridge import LocalBridge, TokenSource
from .config import auto_bridges_enabled
from .killswitch import StopWatcher
from .manager import ensure_bridges, serving_bridges, stop_bridges
from .routing import localize_agent

if typing.TYPE_CHECKING:
    from .runtime import LocalRuntime

logger = logging.getLogger(__name__)

# Runaway guards for sessions whose caller passes no budget: a local session left running (its
# serving process was SIGKILLed, the laptop slept) burns steps against a dead channel until it
# hits these. Explicit values, including None for unbounded, are respected.
DEFAULT_LOCAL_MAX_STEPS = 150
DEFAULT_LOCAL_MAX_TIME_S = 1800.0
REMOTE_CANCEL_TIMEOUT_S = 60.0


def _apply_runaway_budgets(kwargs: typing.Dict[str, typing.Any]) -> None:
    kwargs.setdefault("max_steps", DEFAULT_LOCAL_MAX_STEPS)
    kwargs.setdefault("max_time_s", DEFAULT_LOCAL_MAX_TIME_S)


def _stop_bridges_keeping_error(session_ids: typing.Sequence[str]) -> None:
    """Stop bridges inside an except block; a stop failure is logged so the handled error still propagates."""
    try:
        stop_bridges(session_ids)
    except Exception:
        logger.warning("could not confirm local bridges stopped after a failed session create", exc_info=True)


def _token_source(client_wrapper: typing.Any) -> TokenSource:
    return getattr(client_wrapper, "_async_token", None) or client_wrapper._get_api_key


def _resolve_token(source: TokenSource) -> str:
    """Resolve a token source to a string, wherever the caller runs."""
    token = source() if callable(source) else source
    if not inspect.isawaitable(token):
        return token

    async def consume() -> str:
        return await token

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(consume())
    # This thread already runs a loop; asyncio.run must happen on another one.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(consume())).result()


def _warn_if_overrides_target_user_device(kwargs: typing.Dict[str, typing.Any]) -> None:
    overrides = kwargs.get("overrides")
    if overrides and "user_device" in json.dumps(overrides, default=str):
        logger.warning(
            "session overrides mention user_device, but auto-started bridges are derived from the agent "
            "spec only; serve override-injected environments manually with `hai local browser|desktop|workstation`"
        )


def _localize(
    client_wrapper: typing.Any, runtime: typing.Optional[LocalRuntime], kwargs: typing.Dict[str, typing.Any]
) -> typing.List[LocalBridge]:
    """Spawn bridges for unclaimed user_device environments in an inline agent and stamp their session ids.

    String agent references are left alone: registered agents must carry an explicit session_id on their
    user_device environments, served manually with `hai local browser|desktop|workstation`.
    """
    agent = kwargs.get("agent")
    if agent is None or isinstance(agent, str) or not auto_bridges_enabled():
        return []
    _warn_if_overrides_target_user_device(kwargs)
    if runtime is None:
        localized, bridges = localize_agent(
            agent, api_key=_token_source(client_wrapper), base_url=client_wrapper.get_base_url()
        )
    else:
        localized, bridges = localize_agent(agent, api_key=runtime.api_key, base_url=runtime.base_url)
        for bridge in bridges:
            bridge.verify_runtime = True
    kwargs["agent"] = localized
    return bridges


class _LossWatcher:
    """Watches bridges from startup on and runs a cancel action on the first loss, exactly once,
    whether that loss lands before or after the action is attached."""

    def __init__(self, bridges: typing.Sequence[LocalBridge]) -> None:
        self._lock = threading.Lock()
        self._lost = False
        self._action: typing.Optional[typing.Callable[[], None]] = None
        for bridge in bridges:
            bridge.on_crash = self._fire

    def _fire(self) -> None:
        with self._lock:
            if self._lost:
                return
            self._lost = True
            action = self._action
        if action is not None:
            action()

    def attach(self, action: typing.Callable[[], None]) -> bool:
        """Arm the action for future losses; True when one already landed, so the caller runs it."""
        with self._lock:
            if self._lost:
                return True
            self._action = action
        return False


RemoteCancel = typing.Callable[[str], None]


def _cancel_action(
    cancel_remote: RemoteCancel, bridges: typing.Sequence[LocalBridge], session: typing.Any
) -> typing.Optional[typing.Callable[[], None]]:
    """A bridge that dies mid-session leaves the agent without local control; cancel the session then."""
    session_id = getattr(session, "id", None)
    if session_id is None:
        return None

    def cancel() -> None:
        logger.error("local bridge for session %s crashed; cancelling the session", session_id)
        _deregister_exit_cancel(session_id)
        try:
            cancel_remote(session_id)
        except Exception:
            logger.exception("failed to cancel session %s after its local bridge crashed", session_id)
        finally:
            stop_bridges([bridge.session_id for bridge in bridges])

    return cancel


def _cancel_remote_session(client_wrapper: typing.Any, runtime: typing.Optional[LocalRuntime], session_id: str) -> None:
    """Cancel over a fresh connection, so it works from any thread and at interpreter exit."""
    if runtime is not None:
        http, base_url, api_key = runtime.http_client(), runtime.base_url, runtime.api_key
    else:
        http = httpx.Client(timeout=REMOTE_CANCEL_TIMEOUT_S, follow_redirects=True)
        base_url, api_key = client_wrapper.get_base_url(), _resolve_token(_token_source(client_wrapper))
    with http:
        BaseClient(base_url=base_url, api_key=api_key, httpx_client=http).sessions.cancel_session(session_id)


# Sessions that depend on this process's bridges, cancelled at interpreter exit: the bridges die
# with the process, so leaving those sessions running only burns steps against a dead channel.
_exit_cancels: typing.Dict[str, typing.Callable[[], None]] = {}
_exit_lock = threading.Lock()
_stop_watcher: typing.Optional[StopWatcher] = None


def _ensure_stop_watcher() -> StopWatcher:
    """Arm kill-switch coverage, replacing a fired watcher; a fired one is spent."""
    global _stop_watcher
    with _exit_lock:
        if _stop_watcher is None or not _stop_watcher.active:
            _stop_watcher = StopWatcher(_panic_stop)
        return _stop_watcher


def _register_exit_cancel(cancel_remote: RemoteCancel, session_id: str) -> None:
    def cancel_quietly() -> None:
        # Best effort: the session may have finished long ago; the platform rejects the cancel then.
        try:
            cancel_remote(session_id)
            logger.info("cancelled session %s at exit: its local bridge lives in this process", session_id)
        except Exception as exc:
            logger.debug("exit-time cancel of session %s skipped: %s", session_id, exc)

    with _exit_lock:
        _exit_cancels[session_id] = cancel_quietly
    _ensure_stop_watcher()


def _panic_stop() -> None:
    logger.warning("kill switch fired: cancelling local sessions and stopping bridges")
    _cancel_sessions_at_exit()
    stop_bridges()


def _deregister_exit_cancel(session_id: str) -> None:
    with _exit_lock:
        _exit_cancels.pop(session_id, None)


def _cancel_sessions_at_exit() -> None:
    with _exit_lock:
        cancels = list(_exit_cancels.values())
        _exit_cancels.clear()
    for cancel in cancels:
        cancel()


atexit.register(_cancel_sessions_at_exit)

# The session already ended or is gone: nothing left to stop.
STOPPED_CANCEL_STATUSES = frozenset({404, 409})


@contextlib.contextmanager
def _confirming_stop(session_id: str) -> typing.Iterator[None]:
    """Keep the exit retry registered until the platform confirms the session stopped or had already ended."""
    try:
        yield
    except ApiError as error:
        if error.status_code in STOPPED_CANCEL_STATUSES:
            _deregister_exit_cancel(session_id)
        raise
    _deregister_exit_cancel(session_id)


class _CloseFailures:
    """Cancel errors collected while closing; a session that already ended is not a failure."""

    def __init__(self) -> None:
        self._errors: typing.List[Exception] = []

    @contextlib.contextmanager
    def cancelling(self) -> typing.Iterator[None]:
        try:
            yield
        except ApiError as error:
            if error.status_code not in STOPPED_CANCEL_STATUSES:
                self._errors.append(error)
        except Exception as error:
            self._errors.append(error)

    def raise_any(self) -> None:
        if self._errors:
            raise RuntimeError("Could not confirm all client-owned sessions stopped") from self._errors[0]


class _LocalSessionsState:
    """Bridge and session bookkeeping shared by the sync and async local sessions clients."""

    def __init__(
        self, *, client_wrapper: typing.Any, runtime: typing.Optional[LocalRuntime] = None, auto_bridges: bool = True
    ) -> None:
        super().__init__(client_wrapper=client_wrapper)
        self._runtime = runtime
        self._auto_bridges = auto_bridges
        self._cancel_remote: RemoteCancel = functools.partial(_cancel_remote_session, client_wrapper, runtime)
        self._owned_bridges: typing.Dict[str, typing.List[str]] = {}
        # Sessions this client created on a local runtime; they never keep that runtime alive past close().
        self.own_session_ids: typing.Set[str] = set()

    def _live_sessions(self) -> typing.List[str]:
        """Forget sessions whose bridges all stopped, since each such stop already ended or cancelled its session."""
        for session_id, bridge_ids in list(self._owned_bridges.items()):
            if not serving_bridges(bridge_ids):
                del self._owned_bridges[session_id]
                _deregister_exit_cancel(session_id)
        return list(self._owned_bridges)

    def _track(self, session: typing.Any, started: typing.List[str]) -> None:
        if self._runtime is not None:
            self.own_session_ids.add(str(session.id))
        if started:
            self._owned_bridges[str(session.id)] = started


class LocalSessionsClient(_LocalSessionsState, SessionsClient):
    def close(self) -> None:
        failures = _CloseFailures()
        for session_id in self._live_sessions():
            with failures.cancelling():
                self.cancel_session(session_id)
        failures.raise_any()

    def cancel_session(self, id: str, *, request_options: typing.Optional[RequestOptions] = None) -> None:
        # Stop local execution even if the remote cancellation cannot be delivered.
        owned = self._owned_bridges.get(str(id), [])
        try:
            if owned:
                stop_bridges(owned)
                self._owned_bridges.pop(str(id), None)
        finally:
            with _confirming_stop(str(id)):
                super().cancel_session(id, request_options=request_options)

    @functools.wraps(SessionsClient.create_session)
    def create_session(self, **kwargs: typing.Any) -> typing.Any:
        bridges = _localize(self._raw_client._client_wrapper, self._runtime, kwargs) if self._auto_bridges else []
        if bridges:
            _apply_runaway_budgets(kwargs)
        stop_watcher = _ensure_stop_watcher() if bridges else None
        watcher = _LossWatcher(bridges)
        started = ensure_bridges(bridges)
        try:
            session = super().create_session(**kwargs)
        except BaseException:
            _stop_bridges_keeping_error(started)
            raise
        if bridges:
            cancel = _cancel_action(self._cancel_remote, bridges, session)
            if cancel is not None:
                if watcher.attach(cancel):
                    cancel()
                else:
                    _register_exit_cancel(self._cancel_remote, session.id)
                    if stop_watcher is not None and not stop_watcher.active:
                        # A stop was filed while bridges or the session were starting; apply it now.
                        _panic_stop()
        self._track(session, started)
        return session


class LocalAsyncSessionsClient(_LocalSessionsState, AsyncSessionsClient):
    async def aclose(self) -> None:
        failures = _CloseFailures()
        for session_id in self._live_sessions():
            with failures.cancelling():
                await self.cancel_session(session_id)
        failures.raise_any()

    async def cancel_session(self, id: str, *, request_options: typing.Optional[RequestOptions] = None) -> None:
        owned = self._owned_bridges.get(str(id), [])
        try:
            if owned:
                await asyncio.to_thread(stop_bridges, owned)
                self._owned_bridges.pop(str(id), None)
        finally:
            with _confirming_stop(str(id)):
                await super().cancel_session(id, request_options=request_options)

    @functools.wraps(AsyncSessionsClient.create_session)
    async def create_session(self, **kwargs: typing.Any) -> typing.Any:
        bridges = _localize(self._raw_client._client_wrapper, self._runtime, kwargs) if self._auto_bridges else []
        if bridges:
            _apply_runaway_budgets(kwargs)
        # Native permission prompts must run before bridge startup moves to a worker.
        for bridge in bridges:
            bridge.preflight()
        stop_watcher = _ensure_stop_watcher() if bridges else None
        watcher = _LossWatcher(bridges)
        started = await asyncio.to_thread(ensure_bridges, bridges)
        try:
            session = await super().create_session(**kwargs)
        except BaseException:
            await asyncio.to_thread(_stop_bridges_keeping_error, started)
            raise
        if bridges:
            cancel = _cancel_action(self._cancel_remote, bridges, session)
            if cancel is not None:
                if watcher.attach(cancel):
                    # cancel_session blocks on HTTP; keep it off the event loop thread.
                    await asyncio.to_thread(cancel)
                else:
                    _register_exit_cancel(self._cancel_remote, session.id)
                    if stop_watcher is not None and not stop_watcher.active:
                        # A stop was filed while bridges or the session were starting; apply it now.
                        await asyncio.to_thread(_panic_stop)
        self._track(session, started)
        return session

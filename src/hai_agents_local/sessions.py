"""Sessions clients that auto-start local bridges for user_device environments."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import functools
import hashlib
import hmac
import inspect
import json
import logging
import threading
import types
import typing

import httpx

from hai_agents.base_client import BaseClient
from hai_agents.core.api_error import ApiError
from hai_agents.core.parse_error import ParsingError
from hai_agents.core.request_options import RequestOptions
from hai_agents.polling import is_terminal_session_status
from hai_agents.sessions.client import AsyncSessionsClient, SessionsClient
from hai_agents.sessions.types.send_session_messages_request_body import SendSessionMessagesRequestBody
from hai_agents.types.session_status import SessionStatus

from .bridge import LocalBridge, TokenSource
from .config import auto_bridges_enabled
from .killswitch import StopWatcher
from .manager import ensure_bridges, serving_bridges, stop_bridges
from .routing import Reference, localize_agent, references, split_revision

if typing.TYPE_CHECKING:
    from .runtime import LocalRuntime
    from .runtime.acquire import RuntimeHold

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


def _caller(api_key: TokenSource, base_url: typing.Optional[str]) -> str:
    """Idempotency keys are scoped per caller on the platform, so bridge ids seeded from them must be too."""
    return hmac.new(_resolve_token(api_key).encode(), f"{base_url}".encode(), hashlib.sha256).hexdigest()


def _warn_if_overrides_target_user_device(kwargs: typing.Dict[str, typing.Any]) -> None:
    overrides = kwargs.get("overrides")
    if overrides and "user_device" in json.dumps(overrides, default=str):
        logger.warning(
            "session overrides mention user_device, but auto-started bridges are derived from the agent "
            "spec only; serve override-injected environments manually with `holo local browser|desktop|workstation`"
        )


def _wants_bridges(auto_bridges: bool, kwargs: typing.Dict[str, typing.Any]) -> bool:
    return auto_bridges and kwargs.get("agent") is not None and auto_bridges_enabled()


_LOOKUP_ERRORS = (ApiError, ParsingError, httpx.HTTPError)


def _resolve_references(client_wrapper: typing.Any, agent: typing.Any) -> typing.Dict[Reference, typing.Any]:
    """Fetch the specs behind the names in ``agent``; a name that cannot be fetched gets no bridge."""
    from hai_agents.agents.client import AgentsClient
    from hai_agents.environments.client import EnvironmentsClient

    agents, environments = (
        AgentsClient(client_wrapper=client_wrapper),
        EnvironmentsClient(client_wrapper=client_wrapper),
    )
    resolved: typing.Dict[Reference, typing.Any] = {}
    for reference in references(agent):
        kind, name = reference
        try:
            if kind == "agent":
                agent_name, revision = split_revision(name)
                resolved[reference] = agents.get_agent(agent_name, revision=revision, resolve=True)
            else:
                resolved[reference] = environments.get_environment(name)
        except _LOOKUP_ERRORS as exc:
            logger.debug("cannot fetch %s %r to look for user_device environments: %s", kind, name, exc)
    return resolved


async def _resolve_references_async(
    client_wrapper: typing.Any, agent: typing.Any
) -> typing.Dict[Reference, typing.Any]:
    from hai_agents.agents.client import AsyncAgentsClient
    from hai_agents.environments.client import AsyncEnvironmentsClient

    agents = AsyncAgentsClient(client_wrapper=client_wrapper)
    environments = AsyncEnvironmentsClient(client_wrapper=client_wrapper)

    async def fetch(reference: Reference) -> typing.Any:
        kind, name = reference
        try:
            if kind == "agent":
                agent_name, revision = split_revision(name)
                return await agents.get_agent(agent_name, revision=revision, resolve=True)
            return await environments.get_environment(name)
        except _LOOKUP_ERRORS as exc:
            logger.debug("cannot fetch %s %r to look for user_device environments: %s", kind, name, exc)
            return None

    found = references(agent)
    specs = await asyncio.gather(*(fetch(reference) for reference in found))
    return {reference: spec for reference, spec in zip(found, specs) if spec is not None}


def local_environment_kinds(client: typing.Any, agent: typing.Any) -> typing.List[str]:
    """Kinds of the user_device environments a run of ``agent`` would serve from this machine; fetches named specs."""
    wrapper = client.sessions._client_wrapper
    resolved = _resolve_references(wrapper, agent)
    localized = localize_agent(
        agent, api_key=_token_source(wrapper), base_url=wrapper.get_base_url(), resolved=resolved
    )
    return [bridge.environment_kind for bridge in localized.bridges]


def _localize(
    client_wrapper: typing.Any,
    runtime: typing.Optional[LocalRuntime],
    kwargs: typing.Dict[str, typing.Any],
    resolved: typing.Mapping[Reference, typing.Any],
) -> typing.List[LocalBridge]:
    """Spawn bridges for unclaimed user_device environments and route each one to its bridge; caller overrides win."""
    _warn_if_overrides_target_user_device(kwargs)
    overrides = kwargs.get("overrides") or {}
    if runtime is None:
        api_key, base_url = _token_source(client_wrapper), client_wrapper.get_base_url()
    else:
        api_key, base_url = runtime.api_key, runtime.base_url
    idempotency_key = kwargs.get("idempotency_key")
    localized = localize_agent(
        kwargs["agent"],
        api_key=api_key,
        base_url=base_url,
        resolved=resolved,
        claimed=overrides,
        seed=None if idempotency_key is None else f"{_caller(api_key, base_url)}:{idempotency_key}",
    )
    kwargs["agent"] = localized.agent
    if localized.overrides:
        kwargs["overrides"] = {**localized.overrides, **overrides}
    for bridge in localized.bridges:
        bridge.verify_runtime = runtime is not None
    return localized.bridges


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
    logger.warning("kill switch fired: stopping bridges and cancelling local sessions")
    try:
        stop_bridges()
    finally:
        _cancel_sessions_at_exit()


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
        self, *, client_wrapper: typing.Any, hold: typing.Optional[RuntimeHold] = None, auto_bridges: bool = True
    ) -> None:
        super().__init__(client_wrapper=client_wrapper)
        self._hold = hold
        self._client_wrapper = client_wrapper
        self._auto_bridges = auto_bridges
        self._owned_bridges: typing.Dict[str, typing.List[str]] = {}
        self._served: typing.Dict[str, typing.List[LocalBridge]] = {}
        # Sessions whose bridges stopped because they ended or were cancelled; a message restarts the session, so it
        # serves them again.
        self._stopped: typing.Dict[str, typing.List[LocalBridge]] = {}
        # Sessions this client created on a local runtime; they never keep that runtime alive past close().
        self.own_session_ids: typing.Set[str] = set()

    @contextlib.contextmanager
    def _reviving(self, session_id: str) -> typing.Iterator[typing.List[LocalBridge]]:
        """Bridges a stopped session needs again; kept for the retry if the follow-up fails."""
        bridges = self._stopped.pop(session_id, [])
        try:
            yield bridges
        except BaseException:
            if bridges:
                self._stopped[session_id] = bridges
            raise

    def _retire(self, session_id: str) -> None:
        """Its bridges stopped; keep them for a follow-up, which restarts the session."""
        self._owned_bridges.pop(session_id, None)
        if session_id in self._served:
            self._stopped[session_id] = self._served.pop(session_id)

    @property
    def _runtime(self) -> typing.Optional[LocalRuntime]:
        return None if self._hold is None else self._hold.runtime

    @property
    def _cancel_remote(self) -> RemoteCancel:
        """Bound to the runtime of the moment, so an exit cancel reaches the runtime its session lives on."""
        return functools.partial(_cancel_remote_session, self._client_wrapper, self._runtime)

    def _live_sessions(self) -> typing.List[str]:
        """Forget sessions whose bridges all stopped, since each such stop already ended or cancelled its session."""
        for session_id, bridge_ids in list(self._owned_bridges.items()):
            if not serving_bridges(bridge_ids):
                del self._owned_bridges[session_id]
                _deregister_exit_cancel(session_id)
        return list(self._owned_bridges)

    def _ended_bridges(self, session_id: str, status: SessionStatus) -> typing.List[str]:
        """The bridges to stop when ``status`` shows the session ended; an ended session needs no exit cancel."""
        if not is_terminal_session_status(status.status):
            return []
        _deregister_exit_cancel(session_id)
        return self._owned_bridges.get(session_id, [])

    def _stop_ended(self, session_id: str, owned: typing.List[str]) -> None:
        """An unconfirmed stop stays owned, so close() retries it."""
        try:
            stop_bridges(owned)
        except TimeoutError:
            logger.warning("could not confirm local bridges stopped for ended session %s", session_id, exc_info=True)
        else:
            self._retire(session_id)

    def _track(self, session: typing.Any, bridges: typing.List[LocalBridge], started: typing.List[str]) -> None:
        session_id = getattr(session, "id", None)
        if session_id is None:
            return
        if self._runtime is not None:
            self.own_session_ids.add(str(session_id))
        if started:
            self._owned_bridges[str(session_id)] = started
        if bridges:
            self._served[str(session_id)] = bridges

    def _guard(
        self,
        session: typing.Any,
        bridges: typing.Sequence[LocalBridge],
        watcher: _LossWatcher,
        stop_watcher: typing.Optional[StopWatcher],
    ) -> typing.Optional[typing.Callable[[], None]]:
        """Arm the crash and exit cancels of ``session``; returns a stop that already landed and must run now."""
        cancel = _cancel_action(self._cancel_remote, bridges, session)
        if cancel is None:
            return None
        if watcher.attach(cancel):
            return cancel
        _register_exit_cancel(self._cancel_remote, session.id)
        if stop_watcher is not None and not stop_watcher.active:
            # A stop was filed while bridges or the session were starting.
            return _panic_stop
        return None


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
            self._retire(str(id))
        finally:
            with _confirming_stop(str(id)):
                super().cancel_session(id, request_options=request_options)

    def get_session_status(self, id: str, *, request_options: typing.Optional[RequestOptions] = None) -> SessionStatus:
        status = super().get_session_status(id, request_options=request_options)
        owned = self._ended_bridges(str(id), status)
        if owned:
            self._stop_ended(str(id), owned)
        return status

    @functools.wraps(SessionsClient.create_session)
    def create_session(self, **kwargs: typing.Any) -> typing.Any:
        if self._hold is not None:
            self._hold.reacquire()
        bridges: typing.List[LocalBridge] = []
        if _wants_bridges(self._auto_bridges, kwargs):
            wrapper = self._raw_client._client_wrapper
            bridges = _localize(wrapper, self._runtime, kwargs, _resolve_references(wrapper, kwargs["agent"]))
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
        if bridges and (landed := self._guard(session, bridges, watcher, stop_watcher)):
            landed()
        self._track(session, bridges, started)
        return session

    def send_session_messages(
        self,
        id: str,
        *,
        request: SendSessionMessagesRequestBody,
        request_options: typing.Optional[RequestOptions] = None,
    ) -> None:
        with self._reviving(str(id)) as bridges:
            started: typing.List[str] = []
            if bridges:
                stop_watcher, watcher = _ensure_stop_watcher(), _LossWatcher(bridges)
                started = ensure_bridges(bridges)
            try:
                super().send_session_messages(id, request=request, request_options=request_options)
            except BaseException:
                _stop_bridges_keeping_error(started)
                raise
        if bridges:
            session = types.SimpleNamespace(id=str(id))
            if landed := self._guard(session, bridges, watcher, stop_watcher):
                landed()
            self._track(session, bridges, started)


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
            self._retire(str(id))
        finally:
            with _confirming_stop(str(id)):
                await super().cancel_session(id, request_options=request_options)

    async def get_session_status(
        self, id: str, *, request_options: typing.Optional[RequestOptions] = None
    ) -> SessionStatus:
        status = await super().get_session_status(id, request_options=request_options)
        owned = self._ended_bridges(str(id), status)
        if owned:
            await asyncio.to_thread(self._stop_ended, str(id), owned)
        return status

    @functools.wraps(AsyncSessionsClient.create_session)
    async def create_session(self, **kwargs: typing.Any) -> typing.Any:
        if self._hold is not None:
            await self._hold.reacquire_async()
        bridges: typing.List[LocalBridge] = []
        if _wants_bridges(self._auto_bridges, kwargs):
            wrapper = self._raw_client._client_wrapper
            resolved = await _resolve_references_async(wrapper, kwargs["agent"])
            bridges = _localize(wrapper, self._runtime, kwargs, resolved)
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
        if bridges and (landed := self._guard(session, bridges, watcher, stop_watcher)):
            # Cancelling blocks on HTTP; keep it off the event loop thread.
            await asyncio.to_thread(landed)
        self._track(session, bridges, started)
        return session

    async def send_session_messages(
        self,
        id: str,
        *,
        request: SendSessionMessagesRequestBody,
        request_options: typing.Optional[RequestOptions] = None,
    ) -> None:
        with self._reviving(str(id)) as bridges:
            started: typing.List[str] = []
            if bridges:
                for bridge in bridges:
                    bridge.preflight()
                stop_watcher, watcher = _ensure_stop_watcher(), _LossWatcher(bridges)
                started = await asyncio.to_thread(ensure_bridges, bridges)
            try:
                await super().send_session_messages(id, request=request, request_options=request_options)
            except BaseException:
                await asyncio.to_thread(_stop_bridges_keeping_error, started)
                raise
        if bridges:
            session = types.SimpleNamespace(id=str(id))
            if landed := self._guard(session, bridges, watcher, stop_watcher):
                await asyncio.to_thread(landed)
            self._track(session, bridges, started)

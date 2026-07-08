"""Sessions clients that auto-start local bridges for user_device environments."""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import inspect
import json
import logging
import threading
import typing

from hai_agents.sessions.client import AsyncSessionsClient, SessionsClient

from .bridge import LocalBridge, TokenSource
from .config import auto_bridges_enabled
from .manager import ensure_bridges, stop_bridges
from .routing import localize_agent

logger = logging.getLogger(__name__)


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
            "spec only; serve override-injected environments manually with `hai local browser|desktop`"
        )


def _localize(client_wrapper: typing.Any, kwargs: typing.Dict[str, typing.Any]) -> typing.List[LocalBridge]:
    """Spawn bridges for unclaimed user_device environments in an inline agent and stamp their session ids.

    String agent references are left alone: registered agents must carry an explicit session_id on their
    user_device environments, served manually with `hai local browser|desktop`.
    """
    agent = kwargs.get("agent")
    if agent is None or isinstance(agent, str) or not auto_bridges_enabled():
        return []
    _warn_if_overrides_target_user_device(kwargs)
    localized, bridges = localize_agent(
        agent, api_key=_token_source(client_wrapper), base_url=client_wrapper.get_base_url()
    )
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


def _cancel_action(
    client_wrapper: typing.Any, bridges: typing.Sequence[LocalBridge], session: typing.Any
) -> typing.Optional[typing.Callable[[], None]]:
    """A bridge that dies mid-session leaves the agent without local control; cancel the session then."""
    session_id = getattr(session, "id", None)
    if session_id is None:
        return None

    def cancel() -> None:
        logger.error("local bridge for session %s crashed; cancelling the session", session_id)
        try:
            from hai_agents.client import Client

            api_key = _resolve_token(_token_source(client_wrapper))
            client = Client(api_key=api_key, base_url=client_wrapper.get_base_url())
            client.sessions.cancel_session(session_id)
        except Exception:
            logger.exception("failed to cancel session %s after its local bridge crashed", session_id)
        finally:
            stop_bridges([bridge.session_id for bridge in bridges])

    return cancel


class LocalSessionsClient(SessionsClient):
    @functools.wraps(SessionsClient.create_session)
    def create_session(self, **kwargs: typing.Any) -> typing.Any:
        wrapper = self._raw_client._client_wrapper
        bridges = _localize(wrapper, kwargs)
        watcher = _LossWatcher(bridges)
        started = ensure_bridges(bridges)
        try:
            session = super().create_session(**kwargs)
        except BaseException:
            stop_bridges(started)
            raise
        if bridges:
            cancel = _cancel_action(wrapper, bridges, session)
            if cancel is not None and watcher.attach(cancel):
                cancel()
        return session


class LocalAsyncSessionsClient(AsyncSessionsClient):
    @functools.wraps(AsyncSessionsClient.create_session)
    async def create_session(self, **kwargs: typing.Any) -> typing.Any:
        wrapper = self._raw_client._client_wrapper
        bridges = _localize(wrapper, kwargs)
        watcher = _LossWatcher(bridges)
        started = await asyncio.to_thread(ensure_bridges, bridges)
        try:
            session = await super().create_session(**kwargs)
        except BaseException:
            await asyncio.to_thread(stop_bridges, started)
            raise
        if bridges:
            cancel = _cancel_action(wrapper, bridges, session)
            if cancel is not None and watcher.attach(cancel):
                # cancel_session blocks on HTTP; keep it off the event loop thread.
                await asyncio.to_thread(cancel)
        return session

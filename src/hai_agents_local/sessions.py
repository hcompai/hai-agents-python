"""Sessions clients that auto-start local bridges for user_device environments."""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import inspect
import json
import logging
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


def _cancel_session_on_crash(
    client_wrapper: typing.Any, bridges: typing.Sequence[LocalBridge], session: typing.Any
) -> None:
    """A bridge that dies mid-session leaves the agent without local control; cancel the session then."""
    session_id = getattr(session, "id", None)
    if session_id is None:
        return

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

    for bridge in bridges:
        bridge.on_crash = cancel


class LocalSessionsClient(SessionsClient):
    @functools.wraps(SessionsClient.create_session)
    def create_session(self, **kwargs: typing.Any) -> typing.Any:
        wrapper = self._raw_client._client_wrapper
        bridges = _localize(wrapper, kwargs)
        started = ensure_bridges(bridges)
        try:
            session = super().create_session(**kwargs)
        except BaseException:
            stop_bridges(started)
            raise
        _cancel_session_on_crash(wrapper, bridges, session)
        return session


class LocalAsyncSessionsClient(AsyncSessionsClient):
    @functools.wraps(AsyncSessionsClient.create_session)
    async def create_session(self, **kwargs: typing.Any) -> typing.Any:
        wrapper = self._raw_client._client_wrapper
        bridges = _localize(wrapper, kwargs)
        started = await asyncio.to_thread(ensure_bridges, bridges)
        try:
            session = await super().create_session(**kwargs)
        except BaseException:
            await asyncio.to_thread(stop_bridges, started)
            raise
        _cancel_session_on_crash(wrapper, bridges, session)
        return session

"""Shared session runners used by the CLI and MCP server."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Union

from pydantic import BaseModel, ConfigDict, Field

from hai_agents import Agent, AsyncClient, Client
from hai_agents.polling import SessionRunResult
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.types import Session, TrajectoryEvent

EventHandler = Callable[[TrajectoryEvent], None]
AsyncEventHandler = Callable[[TrajectoryEvent], Awaitable[None]]

DEFAULT_AGENT = "h/web-surfer-holo3-1-35b"
TERMINAL_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted", "idle"})


class RunAgentParams(BaseModel):
    """Parameters for a one-shot agent run.

    Args:
        task: User task to send as the first session message.
        agent: Registered agent name or full inline Agent definition.
        max_steps: Maximum reasoning steps.
        max_time_s: Maximum backend wall-clock seconds.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: str = Field(min_length=1)
    agent: Union[str, Agent] = DEFAULT_AGENT
    max_steps: int = Field(default=20, ge=1, le=200)
    max_time_s: float = Field(default=180.0, gt=0, le=1800)


def run_agent(client: Client, params: RunAgentParams, *, on_event: EventHandler) -> SessionRunResult:
    """Create a session and wait for it to finish.

    Args:
        client: Configured SDK client.
        params: Run configuration.
        on_event: Callback invoked for each streamed event.

    Returns:
        Completed session run result.
    """
    session = client.sessions.create_session(
        agent=params.agent,
        messages=params.task,
        max_steps=params.max_steps,
        max_time_s=params.max_time_s,
    )
    return _wait_for_session(client, session.id, params.max_time_s, on_event)


async def async_run_agent(
    client: AsyncClient, params: RunAgentParams, *, on_event: AsyncEventHandler
) -> SessionRunResult:
    """Async version of `run_agent`.

    Args:
        client: Configured async SDK client.
        params: Run configuration.
        on_event: Async callback invoked for each streamed event.

    Returns:
        Completed session run result.

    Raises:
        asyncio.CancelledError: If the caller cancels the run; the backend
            session is cancelled before re-raising.
    """
    session_id: str | None = None
    try:
        session = await client.sessions.create_session(
            agent=params.agent,
            messages=params.task,
            max_steps=params.max_steps,
            max_time_s=params.max_time_s,
        )
        session_id = session.id
        return await _async_wait_for_session(client, session.id, params.max_time_s, on_event)
    except asyncio.CancelledError:
        if session_id is not None:
            await async_cancel_session(client, session_id)
        raise


def get_session(client: Client, session_id: str) -> Session:
    """Fetch a session.

    Args:
        client: Configured SDK client.
        session_id: Session identifier.

    Returns:
        Session envelope.
    """
    return client.sessions.get_session(session_id)


async def async_get_session(client: AsyncClient, session_id: str) -> Session:
    """Async version of `get_session`.

    Args:
        client: Configured async SDK client.
        session_id: Session identifier.

    Returns:
        Session envelope.
    """
    return await client.sessions.get_session(session_id)


def cancel_session(client: Client, session_id: str) -> None:
    """Cancel a session.

    Args:
        client: Configured SDK client.
        session_id: Session identifier.
    """
    client.sessions.cancel_session(session_id)


async def async_cancel_session(client: AsyncClient, session_id: str) -> None:
    """Async version of `cancel_session`.

    Args:
        client: Configured async SDK client.
        session_id: Session identifier.
    """
    await client.sessions.cancel_session(session_id)


def send_message(client: Client, session_id: str, text: str) -> None:
    """Send a user message to a live session.

    Args:
        client: Configured SDK client.
        session_id: Session identifier.
        text: Message text.
    """
    request = SendSessionMessagesRequestBody_UserMessage(message=text)
    client.sessions.send_session_messages(session_id, request=request)


async def async_send_message(client: AsyncClient, session_id: str, text: str) -> None:
    """Async version of `send_message`.

    Args:
        client: Configured async SDK client.
        session_id: Session identifier.
        text: Message text.
    """
    request = SendSessionMessagesRequestBody_UserMessage(message=text)
    await client.sessions.send_session_messages(session_id, request=request)


def share_session(client: Client, session_id: str) -> str:
    """Share a session and return only the public URL/path.

    Args:
        client: Configured SDK client.
        session_id: Session identifier.

    Returns:
        Share URL/path.
    """
    return client.sessions.share_session(session_id).share_url


async def async_share_session(client: AsyncClient, session_id: str) -> str:
    """Async version of `share_session`.

    Args:
        client: Configured async SDK client.
        session_id: Session identifier.

    Returns:
        Share URL/path.
    """
    link = await client.sessions.share_session(session_id)
    return link.share_url


def _wait_for_session(
    client: Client,
    session_id: str,
    timeout_seconds: float,
    on_event: EventHandler,
) -> SessionRunResult:
    events: list[TrajectoryEvent] = []
    next_from_index = 0
    last_changes = None
    deadline = time.monotonic() + timeout_seconds + 30.0

    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Session {session_id} did not finish within {timeout_seconds}s.")

        changes = client.sessions.get_session_changes(
            session_id,
            from_index=next_from_index,
            include_events=True,
            wait_for_seconds=20,
        )
        if changes is not None:
            last_changes = changes
            for event in changes.new_events or []:
                on_event(event)
                events.append(event)
                next_from_index += 1

        status = client.sessions.get_session_status(session_id)
        if _is_terminal(status.status):
            return SessionRunResult(
                id=session_id,
                status=status.status,
                events=events,
                next_from_index=next_from_index,
                final_changes=_final_changes(client, session_id, last_changes),
            )


async def _async_wait_for_session(
    client: AsyncClient,
    session_id: str,
    timeout_seconds: float,
    on_event: AsyncEventHandler,
) -> SessionRunResult:
    events: list[TrajectoryEvent] = []
    next_from_index = 0
    last_changes = None
    deadline = time.monotonic() + timeout_seconds + 30.0

    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Session {session_id} did not finish within {timeout_seconds}s.")

        changes = await client.sessions.get_session_changes(
            session_id,
            from_index=next_from_index,
            include_events=True,
            wait_for_seconds=20,
        )
        if changes is not None:
            last_changes = changes
            for event in changes.new_events or []:
                await on_event(event)
                events.append(event)
                next_from_index += 1

        status = await client.sessions.get_session_status(session_id)
        if _is_terminal(status.status):
            final_changes = await _async_final_changes(client, session_id, last_changes)
            return SessionRunResult(
                id=session_id,
                status=status.status,
                events=events,
                next_from_index=next_from_index,
                final_changes=final_changes,
            )


def _final_changes(client: Client, session_id: str, last_changes):
    if last_changes is not None and last_changes.answer is not None:
        return last_changes
    fetched = client.sessions.get_session_changes(
        session_id,
        from_index=0,
        include_events=False,
        wait_for_seconds=0,
    )
    return fetched or last_changes


async def _async_final_changes(client: AsyncClient, session_id: str, last_changes):
    if last_changes is not None and last_changes.answer is not None:
        return last_changes
    fetched = await client.sessions.get_session_changes(
        session_id,
        from_index=0,
        include_events=False,
        wait_for_seconds=0,
    )
    return fetched or last_changes


def _is_terminal(status) -> bool:
    return str(getattr(status, "value", status)) in TERMINAL_STATUSES

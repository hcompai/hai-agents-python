"""Convenience helpers for the common create-and-poll session workflow."""

from __future__ import annotations

import typing
from dataclasses import dataclass

from .client import AsyncClient, Client
from .types.trajectory_changes import TrajectoryChanges
from .types.trajectory_changes_answer import TrajectoryChangesAnswer
from .types.trajectory_event import TrajectoryEvent
from .types.trajectory_status import TrajectoryStatus

TERMINAL_SESSION_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted"})


@dataclass(frozen=True)
class SessionRunResult:
    """Result returned by ``run_session_until_done`` and ``wait_for_session``."""

    id: str
    final_changes: TrajectoryChanges
    events: typing.List[TrajectoryEvent]
    next_from_index: int

    @property
    def answer(self) -> typing.Optional[TrajectoryChangesAnswer]:
        """Final answer from the terminal changes batch, if present."""
        return self.final_changes.answer


def is_terminal_session_status(status: typing.Union[TrajectoryStatus, str]) -> bool:
    """Return whether a session status should end a polling loop."""
    return getattr(status, "value", status) in TERMINAL_SESSION_STATUSES


def wait_for_session(
    client: Client,
    id: str,
    *,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: typing.Optional[int] = None,
    max_polls: typing.Optional[int] = None,
) -> SessionRunResult:
    """Long-poll a session until it reaches a terminal status."""
    events: typing.List[TrajectoryEvent] = []
    next_from_index = from_index
    polls = 0

    while max_polls is None or polls < max_polls:
        polls += 1
        changes = client.sessions.get_session_changes(
            id,
            from_index=next_from_index,
            limit=limit,
            include_events=True,
            wait_for_seconds=wait_for_seconds,
        )
        if changes is None:
            continue

        batch = changes.new_events or []
        events.extend(batch)
        next_from_index += len(batch)
        if is_terminal_session_status(changes.status):
            return SessionRunResult(
                id=id, final_changes=changes, events=events, next_from_index=next_from_index
            )

    raise TimeoutError(f"Session {id} did not reach a terminal status before max_polls={max_polls}")


def run_session_until_done(
    client: Client,
    *,
    wait_for_seconds: int = 20,
    max_polls: typing.Optional[int] = None,
    **create_kwargs: typing.Any,
) -> SessionRunResult:
    """Create a session, then long-poll ``/changes`` until it completes or fails."""
    session = client.sessions.create_session(**create_kwargs)
    return wait_for_session(client, session.id, wait_for_seconds=wait_for_seconds, max_polls=max_polls)


async def async_wait_for_session(
    client: AsyncClient,
    id: str,
    *,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: typing.Optional[int] = None,
    max_polls: typing.Optional[int] = None,
) -> SessionRunResult:
    """Async version of ``wait_for_session``."""
    events: typing.List[TrajectoryEvent] = []
    next_from_index = from_index
    polls = 0

    while max_polls is None or polls < max_polls:
        polls += 1
        changes = await client.sessions.get_session_changes(
            id,
            from_index=next_from_index,
            limit=limit,
            include_events=True,
            wait_for_seconds=wait_for_seconds,
        )
        if changes is None:
            continue

        batch = changes.new_events or []
        events.extend(batch)
        next_from_index += len(batch)
        if is_terminal_session_status(changes.status):
            return SessionRunResult(
                id=id, final_changes=changes, events=events, next_from_index=next_from_index
            )

    raise TimeoutError(f"Session {id} did not reach a terminal status before max_polls={max_polls}")


async def async_run_session_until_done(
    client: AsyncClient,
    *,
    wait_for_seconds: int = 20,
    max_polls: typing.Optional[int] = None,
    **create_kwargs: typing.Any,
) -> SessionRunResult:
    """Async version of ``run_session_until_done``."""
    session = await client.sessions.create_session(**create_kwargs)
    return await async_wait_for_session(
        client, session.id, wait_for_seconds=wait_for_seconds, max_polls=max_polls
    )

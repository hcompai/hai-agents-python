"""Convenience helpers for the common create-and-poll session workflow."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from hai_agents.api.sessions import create_session, get_session_changes
from hai_agents.client import AuthenticatedClient
from hai_agents.models.http_validation_error import HTTPValidationError
from hai_agents.models.session import Session
from hai_agents.models.session_request import SessionRequest
from hai_agents.models.trajectory_changes import TrajectoryChanges
from hai_agents.models.trajectory_event import TrajectoryEvent
from hai_agents.models.trajectory_status import TrajectoryStatus
from hai_agents.types import UNSET, Unset

TERMINAL_SESSION_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted"})


@dataclass(frozen=True)
class SessionRunResult:
    """Result returned by ``run_session_until_done`` and ``wait_for_session``."""

    id: UUID
    final_changes: TrajectoryChanges
    events: list[TrajectoryEvent]
    next_from_index: int

    @property
    def answer(self) -> object:
        """Final answer from the terminal changes batch, if present."""
        return None if isinstance(self.final_changes.answer, Unset) else self.final_changes.answer


def is_terminal_session_status(status: TrajectoryStatus | str) -> bool:
    """Return whether a session status should end a polling loop."""
    value = status.value if isinstance(status, TrajectoryStatus) else status
    return value in TERMINAL_SESSION_STATUSES


def _new_events(changes: TrajectoryChanges) -> list[TrajectoryEvent]:
    return [] if changes.new_events is None or isinstance(changes.new_events, Unset) else changes.new_events


def _ensure_session(value: HTTPValidationError | Session | None) -> Session:
    if isinstance(value, Session):
        return value
    raise RuntimeError(f"Could not create session: {value!r}")


def _ensure_changes(value: object) -> TrajectoryChanges | None:
    if value is None:
        return None
    if isinstance(value, TrajectoryChanges):
        return value
    raise RuntimeError(f"Unexpected session changes response: {value!r}")


def wait_for_session(  # noqa: PLR0913
    id: UUID,
    *,
    client: AuthenticatedClient,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: int | None | Unset = UNSET,
    max_polls: int | None = None,
) -> SessionRunResult:
    """Long-poll a session until it reaches a terminal status."""
    events: list[TrajectoryEvent] = []
    next_from_index = from_index
    polls = 0

    while max_polls is None or polls < max_polls:
        polls += 1
        changes = _ensure_changes(
            get_session_changes.sync(
                id,
                client=client,
                from_index=next_from_index,
                limit=limit,
                include_events=True,
                wait_for_seconds=wait_for_seconds,
            )
        )
        if changes is None:
            continue

        batch = _new_events(changes)
        events.extend(batch)
        next_from_index += len(batch)
        if is_terminal_session_status(changes.status):
            return SessionRunResult(
                id=id,
                final_changes=changes,
                events=events,
                next_from_index=next_from_index,
            )

    raise TimeoutError(f"Session {id} did not reach a terminal status before max_polls={max_polls}")


async def async_wait_for_session(  # noqa: PLR0913
    id: UUID,
    *,
    client: AuthenticatedClient,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: int | None | Unset = UNSET,
    max_polls: int | None = None,
) -> SessionRunResult:
    """Async version of ``wait_for_session``."""
    events: list[TrajectoryEvent] = []
    next_from_index = from_index
    polls = 0

    while max_polls is None or polls < max_polls:
        polls += 1
        changes = _ensure_changes(
            await get_session_changes.asyncio(
                id,
                client=client,
                from_index=next_from_index,
                limit=limit,
                include_events=True,
                wait_for_seconds=wait_for_seconds,
            )
        )
        if changes is None:
            continue

        batch = _new_events(changes)
        events.extend(batch)
        next_from_index += len(batch)
        if is_terminal_session_status(changes.status):
            return SessionRunResult(
                id=id,
                final_changes=changes,
                events=events,
                next_from_index=next_from_index,
            )

    raise TimeoutError(f"Session {id} did not reach a terminal status before max_polls={max_polls}")


def run_session_until_done(
    *,
    client: AuthenticatedClient,
    body: SessionRequest,
    idempotency_key: None | str | Unset = UNSET,
    wait_for_seconds: int = 20,
    max_polls: int | None = None,
) -> SessionRunResult:
    """Create a session, then long-poll ``/changes`` until it completes or fails."""
    session = _ensure_session(create_session.sync(client=client, body=body, idempotency_key=idempotency_key))
    return wait_for_session(
        session.id,
        client=client,
        wait_for_seconds=wait_for_seconds,
        max_polls=max_polls,
    )


async def async_run_session_until_done(
    *,
    client: AuthenticatedClient,
    body: SessionRequest,
    idempotency_key: None | str | Unset = UNSET,
    wait_for_seconds: int = 20,
    max_polls: int | None = None,
) -> SessionRunResult:
    """Async version of ``run_session_until_done``."""
    session = _ensure_session(await create_session.asyncio(client=client, body=body, idempotency_key=idempotency_key))
    return await async_wait_for_session(
        session.id,
        client=client,
        wait_for_seconds=wait_for_seconds,
        max_polls=max_polls,
    )

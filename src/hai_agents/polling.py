"""Convenience helpers for the common create-and-poll session workflow."""

from __future__ import annotations

import asyncio
import json
import time
import typing
from dataclasses import dataclass

import pydantic
import typing_extensions

from .types.session_request_agent import SessionRequestAgent
from .types.session_request_messages import SessionRequestMessages
from .types.trajectory_changes import TrajectoryChanges
from .types.trajectory_changes_answer import TrajectoryChangesAnswer
from .types.trajectory_event import TrajectoryEvent
from .types.trajectory_status import TrajectoryStatus

# Type-only: the client subclasses import from this module, so importing them at
# runtime here would be circular. Annotations are strings (PEP 563), so this is safe.
if typing.TYPE_CHECKING:
    from .client import AsyncClient, Client
    from .types.session import Session
    from .types.session_status import SessionStatus

TERMINAL_SESSION_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted"})

# Server rejects request bodies above this size; enforced client-side for a clear early error.
MAX_REQUEST_BYTES = 5 * 1024 * 1024


class CreateSessionParams(typing_extensions.TypedDict, total=False):
    """Typed ``create_session`` kwargs; mirror new ``SessionRequest`` fields here to keep autocomplete."""

    agent: typing_extensions.Required[SessionRequestAgent]
    idempotency_key: typing.Optional[str]
    messages: typing.Optional[SessionRequestMessages]
    overrides: typing.Optional[typing.Dict[str, typing.Any]]
    max_steps: typing.Optional[int]
    max_time_s: typing.Optional[float]
    idle_timeout_s: typing.Optional[int]
    group_id: typing.Optional[str]
    parent_session_id: typing.Optional[str]


AnswerT = typing_extensions.TypeVar("AnswerT", default=TrajectoryChangesAnswer)


class AnswerValidationError(ValueError):
    """The session's final answer did not match the requested ``answer_schema``."""

    def __init__(self, raw: typing.Any, model: typing.Type[pydantic.BaseModel], error: Exception) -> None:
        self.raw = raw
        super().__init__(f"Final answer does not match {model.__name__}: {error}")


@dataclass(frozen=True)
class SessionRunResult(typing.Generic[AnswerT]):
    """Result returned by ``run_session`` and ``wait_for_session``.

    ``answer`` is the validated ``answer_schema`` instance when one was requested and the
    session completed; otherwise the raw wire value (also at ``final_changes.answer``).
    """

    id: str
    status: TrajectoryStatus
    events: typing.List[TrajectoryEvent]
    next_from_index: int
    final_changes: typing.Optional[TrajectoryChanges] = None
    answer: typing.Optional[AnswerT] = None

    def __post_init__(self) -> None:
        if self.answer is None and self.final_changes is not None:
            object.__setattr__(self, "answer", self.final_changes.answer)


def _attach_answer_schema(params: typing.Dict[str, typing.Any], model: typing.Type[pydantic.BaseModel]) -> None:
    """Bind the model's JSON schema as the agent's ``answer_format``."""
    schema = model.model_json_schema()
    agent = params.get("agent")
    if isinstance(agent, str):
        overrides = dict(params.get("overrides") or {})
        if overrides.get("agent.answer_format") is not None:
            raise ValueError("answer_schema conflicts with overrides['agent.answer_format']; pass only one.")
        overrides["agent.answer_format"] = schema
        params["overrides"] = overrides
    elif isinstance(agent, dict):
        if agent.get("answer_format") is not None:
            raise ValueError("answer_schema conflicts with agent['answer_format']; pass only one.")
        params["agent"] = {**agent, "answer_format": schema}
    elif isinstance(agent, pydantic.BaseModel):
        if getattr(agent, "answer_format", None) is not None:
            raise ValueError("answer_schema conflicts with agent.answer_format; pass only one.")
        params["agent"] = agent.model_copy(update={"answer_format": schema})
    else:
        raise TypeError(f"answer_schema requires an agent reference, got {type(agent).__name__}.")


def _parse_answer(
    raw: typing.Any,
    status: typing.Union[TrajectoryStatus, str],
    model: typing.Optional[typing.Type[pydantic.BaseModel]],
) -> typing.Any:
    """Validate a completed session's answer into ``model``; non-completed answers pass through raw."""
    if model is None or raw is None or getattr(status, "value", status) != "completed":
        return raw
    try:
        return model.model_validate(raw)
    except pydantic.ValidationError as exc:
        raise AnswerValidationError(raw, model, exc) from exc


def is_terminal_session_status(status: typing.Union[TrajectoryStatus, str]) -> bool:
    """Return whether a session status should end a polling loop."""
    return getattr(status, "value", status) in TERMINAL_SESSION_STATUSES


def _request_bytes(payload: typing.Any) -> int:
    def default(obj: typing.Any) -> typing.Any:
        dump = getattr(obj, "model_dump", None)
        return dump(mode="json") if callable(dump) else str(obj)

    return len(json.dumps(payload, default=default).encode("utf-8"))


def assert_request_under_limit(payload: typing.Any, max_bytes: int = MAX_REQUEST_BYTES) -> None:
    """Raise if a request body exceeds ``max_bytes`` once serialized to JSON."""
    size = _request_bytes(payload)
    if size > max_bytes:
        raise ValueError(
            f"Request payload is {size / 1024 / 1024:.2f}MB, over the "
            f"{max_bytes / 1024 / 1024:.2f}MB limit. Downscale images before sending."
        )


def _final_changes(
    client: Client, id: str, last_changes: typing.Optional[TrajectoryChanges], limit: typing.Optional[int]
) -> typing.Optional[TrajectoryChanges]:
    """The terminal answer lives in ``/changes``; fetch it once if streaming didn't surface it."""
    if last_changes is not None and last_changes.answer is not None:
        return last_changes
    fetched = client.sessions.get_session_changes(
        id, from_index=0, limit=limit, include_events=False, wait_for_seconds=0
    )
    return fetched or last_changes


def wait_for_session(
    client: Client,
    id: str,
    *,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: typing.Optional[int] = None,
    include_events: bool = True,
    timeout_seconds: typing.Optional[float] = None,
    poll_backoff_seconds: float = 0.0,
    max_polls: typing.Optional[int] = None,
    answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
) -> SessionRunResult[AnswerT]:
    """Poll a session until it reaches a terminal status.

    Terminal state is read from ``/status`` (authoritative); ``/changes`` only feeds
    events and the final answer, since it 204s whenever no new events exist past
    ``from_index`` -- even after the session has finished.
    """
    events: typing.List[TrajectoryEvent] = []
    next_from_index = from_index
    last_changes: typing.Optional[TrajectoryChanges] = None
    polls = 0
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while max_polls is None or polls < max_polls:
        polls += 1
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"Session {id} did not reach a terminal status within {timeout_seconds}s")

        if include_events:
            changes = client.sessions.get_session_changes(
                id,
                from_index=next_from_index,
                limit=limit,
                include_events=True,
                wait_for_seconds=wait_for_seconds,
            )
            if changes is not None:
                last_changes = changes
                batch = changes.new_events or []
                events.extend(batch)
                next_from_index += len(batch)

        status = client.sessions.get_session_status(id)
        if is_terminal_session_status(status.status):
            changes = _final_changes(client, id, last_changes, limit)
            raw = changes.answer if changes is not None else None
            return SessionRunResult(
                id=id,
                status=status.status,
                events=events,
                next_from_index=next_from_index,
                final_changes=changes,
                answer=_parse_answer(raw, status.status, answer_schema),
            )

        # The long-poll above paces the loop when streaming events; otherwise sleep.
        if not include_events:
            time.sleep(poll_backoff_seconds or wait_for_seconds)
        elif poll_backoff_seconds > 0:
            time.sleep(poll_backoff_seconds)

    raise TimeoutError(f"Session {id} did not reach a terminal status before max_polls={max_polls}")


def run_session(
    client: Client,
    *,
    wait_for_seconds: int = 20,
    include_events: bool = True,
    timeout_seconds: typing.Optional[float] = None,
    poll_backoff_seconds: float = 0.0,
    max_polls: typing.Optional[int] = None,
    answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
    **create_params: typing_extensions.Unpack[CreateSessionParams],
) -> SessionRunResult[AnswerT]:
    """Create a session, then poll until it completes or fails.

    ``answer_schema`` binds a pydantic model as the agent's ``answer_format`` and
    validates the final answer back into it: ``result.answer`` is a model instance.
    """
    params: typing.Dict[str, typing.Any] = dict(create_params)
    if answer_schema is not None:
        _attach_answer_schema(params, answer_schema)
    assert_request_under_limit(params)
    session = client.sessions.create_session(**params)
    return wait_for_session(
        client,
        session.id,
        wait_for_seconds=wait_for_seconds,
        include_events=include_events,
        timeout_seconds=timeout_seconds,
        poll_backoff_seconds=poll_backoff_seconds,
        max_polls=max_polls,
        answer_schema=answer_schema,
    )


async def _async_final_changes(
    client: AsyncClient, id: str, last_changes: typing.Optional[TrajectoryChanges], limit: typing.Optional[int]
) -> typing.Optional[TrajectoryChanges]:
    """Async version of ``_final_changes``."""
    if last_changes is not None and last_changes.answer is not None:
        return last_changes
    fetched = await client.sessions.get_session_changes(
        id, from_index=0, limit=limit, include_events=False, wait_for_seconds=0
    )
    return fetched or last_changes


async def async_wait_for_session(
    client: AsyncClient,
    id: str,
    *,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: typing.Optional[int] = None,
    include_events: bool = True,
    timeout_seconds: typing.Optional[float] = None,
    poll_backoff_seconds: float = 0.0,
    max_polls: typing.Optional[int] = None,
    answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
) -> SessionRunResult[AnswerT]:
    """Async version of ``wait_for_session``."""
    events: typing.List[TrajectoryEvent] = []
    next_from_index = from_index
    last_changes: typing.Optional[TrajectoryChanges] = None
    polls = 0
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while max_polls is None or polls < max_polls:
        polls += 1
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"Session {id} did not reach a terminal status within {timeout_seconds}s")

        if include_events:
            changes = await client.sessions.get_session_changes(
                id,
                from_index=next_from_index,
                limit=limit,
                include_events=True,
                wait_for_seconds=wait_for_seconds,
            )
            if changes is not None:
                last_changes = changes
                batch = changes.new_events or []
                events.extend(batch)
                next_from_index += len(batch)

        status = await client.sessions.get_session_status(id)
        if is_terminal_session_status(status.status):
            changes = await _async_final_changes(client, id, last_changes, limit)
            raw = changes.answer if changes is not None else None
            return SessionRunResult(
                id=id,
                status=status.status,
                events=events,
                next_from_index=next_from_index,
                final_changes=changes,
                answer=_parse_answer(raw, status.status, answer_schema),
            )

        if not include_events:
            await asyncio.sleep(poll_backoff_seconds or wait_for_seconds)
        elif poll_backoff_seconds > 0:
            await asyncio.sleep(poll_backoff_seconds)

    raise TimeoutError(f"Session {id} did not reach a terminal status before max_polls={max_polls}")


async def async_run_session(
    client: AsyncClient,
    *,
    wait_for_seconds: int = 20,
    include_events: bool = True,
    timeout_seconds: typing.Optional[float] = None,
    poll_backoff_seconds: float = 0.0,
    max_polls: typing.Optional[int] = None,
    answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
    **create_params: typing_extensions.Unpack[CreateSessionParams],
) -> SessionRunResult[AnswerT]:
    """Async version of ``run_session``."""
    params: typing.Dict[str, typing.Any] = dict(create_params)
    if answer_schema is not None:
        _attach_answer_schema(params, answer_schema)
    assert_request_under_limit(params)
    session = await client.sessions.create_session(**params)
    return await async_wait_for_session(
        client,
        session.id,
        wait_for_seconds=wait_for_seconds,
        include_events=include_events,
        timeout_seconds=timeout_seconds,
        poll_backoff_seconds=poll_backoff_seconds,
        max_polls=max_polls,
        answer_schema=answer_schema,
    )


class SessionHandle:
    """A created session bound to its client: object-oriented sugar over the polling helpers."""

    def __init__(
        self,
        client: Client,
        id: str,
        answer_schema: typing.Optional[typing.Type[pydantic.BaseModel]] = None,
    ) -> None:
        self._client = client
        self._answer_schema = answer_schema
        self.id = id

    def get(self) -> Session:
        return self._client.sessions.get_session(self.id)

    def status(self) -> SessionStatus:
        return self._client.sessions.get_session_status(self.id)

    def changes(self, *, from_index: int = 0, **kwargs: typing.Any) -> typing.Optional[TrajectoryChanges]:
        return self._client.sessions.get_session_changes(self.id, from_index=from_index, **kwargs)

    def send_message(self, message: typing.Any) -> None:
        self._client.sessions.send_session_messages(self.id, request=message)

    def pause(self) -> None:
        self._client.sessions.pause_session(self.id)

    def resume(self) -> None:
        self._client.sessions.resume_session(self.id)

    def cancel(self) -> None:
        self._client.sessions.cancel_session(self.id)

    def force_answer(self) -> None:
        self._client.sessions.force_session_answer(self.id)

    def wait_for_completion(self, **kwargs: typing.Any) -> SessionRunResult:
        """Block until the session reaches a terminal status; returns the result and final answer."""
        kwargs.setdefault("answer_schema", self._answer_schema)
        return wait_for_session(self._client, self.id, **kwargs)


class AsyncSessionHandle:
    """Async version of :class:`SessionHandle`."""

    def __init__(
        self,
        client: AsyncClient,
        id: str,
        answer_schema: typing.Optional[typing.Type[pydantic.BaseModel]] = None,
    ) -> None:
        self._client = client
        self._answer_schema = answer_schema
        self.id = id

    async def get(self) -> Session:
        return await self._client.sessions.get_session(self.id)

    async def status(self) -> SessionStatus:
        return await self._client.sessions.get_session_status(self.id)

    async def changes(self, *, from_index: int = 0, **kwargs: typing.Any) -> typing.Optional[TrajectoryChanges]:
        return await self._client.sessions.get_session_changes(self.id, from_index=from_index, **kwargs)

    async def send_message(self, message: typing.Any) -> None:
        await self._client.sessions.send_session_messages(self.id, request=message)

    async def pause(self) -> None:
        await self._client.sessions.pause_session(self.id)

    async def resume(self) -> None:
        await self._client.sessions.resume_session(self.id)

    async def cancel(self) -> None:
        await self._client.sessions.cancel_session(self.id)

    async def force_answer(self) -> None:
        await self._client.sessions.force_session_answer(self.id)

    async def wait_for_completion(self, **kwargs: typing.Any) -> SessionRunResult:
        """Block until the session reaches a terminal status; returns the result and final answer."""
        kwargs.setdefault("answer_schema", self._answer_schema)
        return await async_wait_for_session(self._client, self.id, **kwargs)

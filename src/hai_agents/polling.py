"""Convenience helpers for the common create-and-poll session workflow."""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import json
import time
import typing
from dataclasses import dataclass

import pydantic
import typing_extensions

from .core.api_error import ApiError
from .core.request_options import RequestOptions
from .tools import Tool, ToolInput, as_tools
from .types.session_request_agent import SessionRequestAgent
from .types.session_request_messages import SessionRequestMessages
from .types.session_changes import SessionChanges
from .types.session_changes_answer import SessionChangesAnswer
from .types.session_event import SessionEvent
from .types.trajectory_status import TrajectoryStatus

# Type-only: the client subclasses import from this module, so importing them at
# runtime here would be circular. Annotations are strings (PEP 563), so this is safe.
if typing.TYPE_CHECKING:
    from .client import AsyncClient, Client
    from .types.session import Session
    from .types.session_status import SessionStatus

TERMINAL_SESSION_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted"})

# Polling also stops on "idle": the agent finished its turn and is waiting for the next
# user message, which a one-shot wait will never send.
SETTLED_SESSION_STATUSES = TERMINAL_SESSION_STATUSES | {"idle"}

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


AnswerT = typing_extensions.TypeVar("AnswerT", default=SessionChangesAnswer)


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
    events: typing.List[SessionEvent]
    next_from_index: int
    final_changes: typing.Optional[SessionChanges] = None
    answer: typing.Optional[AnswerT] = None

    def __post_init__(self) -> None:
        if self.answer is None and self.final_changes is not None:
            object.__setattr__(self, "answer", self.final_changes.answer)


def _attach_answer_schema(params: typing.Dict[str, typing.Any], model: typing.Type[typing.Any]) -> None:
    """Bind the model's JSON schema as the agent's ``answer_format``."""
    if not (isinstance(model, type) and issubclass(model, pydantic.BaseModel)):
        raise TypeError(f"answer_schema must be a pydantic.BaseModel subclass, got {model!r}.")
    schema = model.model_json_schema()
    if (params.get("overrides") or {}).get("agent.answer_format") is not None:
        raise ValueError("answer_schema conflicts with overrides['agent.answer_format']; pass only one.")
    agent = params.get("agent")
    if isinstance(agent, str):
        overrides = dict(params.get("overrides") or {})
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
    status: TrajectoryStatus,
    model: typing.Optional[typing.Type[typing.Any]],
) -> typing.Any:
    """Validate a completed or idle session's answer into ``model``; other answers pass through raw.

    An idle session may legitimately have no answer yet, so ``None`` passes through;
    a completed session without a valid answer raises.
    """
    if model is None or status not in ("completed", "idle"):
        return raw
    if status == "idle" and raw is None:
        return None
    try:
        if isinstance(raw, str):
            return model.model_validate_json(raw)
        return model.model_validate(raw)
    except pydantic.ValidationError as exc:
        raise AnswerValidationError(raw, model, exc) from exc


def is_terminal_session_status(status: TrajectoryStatus) -> bool:
    """Return whether a session status is terminal."""
    return status in TERMINAL_SESSION_STATUSES


def is_settled_session_status(status: TrajectoryStatus) -> bool:
    """Return whether a session status should end a polling loop."""
    return status in SETTLED_SESSION_STATUSES


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


def _attach_tool_definitions(create_params: typing.Dict[str, typing.Any], tools: typing.Sequence[Tool]) -> None:
    """Carry the tool definitions via the ``agent.tools`` override; the server applies it to referenced and inline agents alike."""
    overrides = dict(create_params.get("overrides") or {})
    overrides["agent.tools"] = [t.definition() for t in tools]
    create_params["overrides"] = overrides


def _latest_pending_tool_calls(
    batch: typing.Sequence[SessionEvent],
    previous: typing.List[typing.Dict[str, typing.Any]],
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Pending custom tool calls per the latest ``ActiveStateChangeEvent``.

    The agent re-publishes the surviving list whenever a call settles, so the
    latest event is the source of truth; ``previous`` carries it across polls
    whose batches contain no state change.
    """
    calls = previous
    for event in batch:
        if event.type != "ActiveStateChangeEvent":
            continue
        data = event.data
        if hasattr(data, "model_dump"):
            data = data.model_dump()
        if not isinstance(data, dict):
            data = {}
        if data.get("state") == "awaiting_tool_results":
            calls = [c.model_dump() if hasattr(c, "model_dump") else c for c in data.get("pending_tool_calls") or []]
        else:
            calls = []
    return calls


def _json_safe(value: typing.Any) -> typing.Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _tool_req(call: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
    return {"tool_name": call.get("tool_name", ""), "args": call.get("args") or {}, "id": call.get("id")}


def _call_key(call: typing.Dict[str, typing.Any]) -> str:
    """Dedup key for an advertised call: its id, or a content signature when id is null."""
    cid = call.get("id")
    if cid is not None:
        return str(cid)
    return json.dumps({"tool_name": call.get("tool_name", ""), "args": call.get("args") or {}}, sort_keys=True, default=str)


def _tool_result_payload(call: typing.Dict[str, typing.Any], result: typing.Any, is_error: bool) -> typing.Dict[str, typing.Any]:
    if is_error:
        return {"kind": "error_event", "error": str(result), "origin": "client", "tool_req": _tool_req(call)}
    return {"kind": "tool_result", "tool_req": _tool_req(call), "result": _json_safe(result)}


def _execute_tool_call(
    tools_by_name: typing.Mapping[str, Tool], call: typing.Dict[str, typing.Any]
) -> typing.Dict[str, typing.Any]:
    """Run one pending call locally and shape the ``tool_result`` payload."""
    name = call.get("tool_name", "")
    local_tool = tools_by_name.get(name)
    result: typing.Any
    is_error = True
    if local_tool is None:
        result = f"Tool {name!r} is not registered with this client."
    else:
        try:
            result = local_tool.fn(**(call.get("args") or {}))
            if inspect.isawaitable(result):
                result = _run_awaitable(result)
        except Exception as exc:
            result = f"{type(exc).__name__}: {exc}"
        else:
            is_error = False
    return _tool_result_payload(call, result, is_error)


async def _await_result(value: typing.Awaitable[typing.Any]) -> typing.Any:
    return await value


def _run_awaitable(value: typing.Awaitable[typing.Any]) -> typing.Any:
    """``asyncio.run`` fails inside a running loop (e.g. notebooks); run on a fresh thread there."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await_result(value))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _await_result(value)).result()


async def _async_execute_tool_call(
    tools_by_name: typing.Mapping[str, Tool], call: typing.Dict[str, typing.Any]
) -> typing.Dict[str, typing.Any]:
    """Async version of ``_execute_tool_call``; awaits coroutine tools."""
    name = call.get("tool_name", "")
    local_tool = tools_by_name.get(name)
    result: typing.Any
    is_error = True
    if local_tool is None:
        result = f"Tool {name!r} is not registered with this client."
    else:
        try:
            result = local_tool.fn(**(call.get("args") or {}))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            result = f"{type(exc).__name__}: {exc}"
        else:
            is_error = False
    return _tool_result_payload(call, result, is_error)


def _tool_results_body(results: typing.List[typing.Dict[str, typing.Any]]) -> typing.Dict[str, typing.Any]:
    return results[0] if len(results) == 1 else {"type": "batch", "results": results}


def _raise_unless_posted(response: typing.Any) -> None:
    """409 means the session finished and resolved the calls itself; the status poll will exit the loop."""
    if 200 <= response.status_code < 300 or response.status_code == 409:
        return
    raise ApiError(status_code=response.status_code, headers=dict(response.headers), body=response.text)


def _recover_pending_tool_calls(client: Client, id: str) -> typing.List[typing.Dict[str, typing.Any]]:
    """A wait that joins mid-stream may start past the advertising event; replay from 0 to find the latest batch."""
    changes = client.sessions.get_session_changes(id, from_index=0, limit=None, include_events=True, wait_for_seconds=0)
    return _latest_pending_tool_calls(changes.new_events or [], []) if changes is not None else []


async def _async_recover_pending_tool_calls(client: AsyncClient, id: str) -> typing.List[typing.Dict[str, typing.Any]]:
    changes = await client.sessions.get_session_changes(
        id, from_index=0, limit=None, include_events=True, wait_for_seconds=0
    )
    return _latest_pending_tool_calls(changes.new_events or [], []) if changes is not None else []


def _is_transient(status_code: int) -> bool:
    return status_code in (408, 429) or status_code >= 500


def _post_tool_results(client: Client, id: str, results: typing.List[typing.Dict[str, typing.Any]]) -> None:
    # The shared client would retry 409s; here a 409 is a final answer (session settled), so retry transient codes only.
    for attempt in range(3):
        response = client._client_wrapper.httpx_client.request(
            f"api/v2/sessions/{id}/tool_results",
            method="POST",
            json=_tool_results_body(results),
            headers={"content-type": "application/json"},
            request_options=RequestOptions(max_retries=0),
        )
        if not _is_transient(response.status_code) or attempt == 2:
            break
        time.sleep(min(0.5 * 2**attempt, 2.0))
    _raise_unless_posted(response)


async def _async_post_tool_results(
    client: AsyncClient, id: str, results: typing.List[typing.Dict[str, typing.Any]]
) -> None:
    for attempt in range(3):
        response = await client._client_wrapper.httpx_client.request(
            f"api/v2/sessions/{id}/tool_results",
            method="POST",
            json=_tool_results_body(results),
            headers={"content-type": "application/json"},
            request_options=RequestOptions(max_retries=0),
        )
        if not _is_transient(response.status_code) or attempt == 2:
            break
        await asyncio.sleep(min(0.5 * 2**attempt, 2.0))
    _raise_unless_posted(response)


def _final_changes(
    client: Client, id: str, last_changes: typing.Optional[SessionChanges], limit: typing.Optional[int]
) -> typing.Optional[SessionChanges]:
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
    tools: typing.Optional[typing.Sequence[ToolInput]] = None,
) -> SessionRunResult[AnswerT]:
    """Poll a session until it settles (terminal, or idle awaiting the next message), running custom tools along the way.

    Status is read from ``/status`` (authoritative); ``/changes`` only feeds
    events and the final answer, since it 204s whenever no new events exist past
    ``from_index`` -- even after the session has finished.
    """
    tools_by_name = {t.name: t for t in as_tools(tools)} if tools else {}
    if tools_by_name and not include_events:
        raise ValueError("tools require include_events=True: pending calls arrive on the event stream.")
    answered: typing.Set[str] = set()
    advertised: typing.List[typing.Dict[str, typing.Any]] = []
    events: typing.List[SessionEvent] = []
    next_from_index = from_index
    last_changes: typing.Optional[SessionChanges] = None
    polls = 0
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while max_polls is None or polls < max_polls:
        polls += 1
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"Session {id} did not settle within {timeout_seconds}s")

        batch: typing.List[SessionEvent] = []
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
        if is_settled_session_status(status.status):
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

        if tools_by_name:
            advertised = _latest_pending_tool_calls(batch, advertised)
            # Status gate: on a replayed stream the live status decides whether calls are still open.
            if status.status == "awaiting_tool_results":
                if not advertised:
                    advertised = _recover_pending_tool_calls(client, id)
                calls = [c for c in advertised if _call_key(c) not in answered]
                if calls:
                    _post_tool_results(client, id, [_execute_tool_call(tools_by_name, c) for c in calls])
                    answered.update(_call_key(c) for c in calls)

        # The long-poll above paces the loop when streaming events; otherwise sleep.
        if not include_events:
            time.sleep(poll_backoff_seconds or wait_for_seconds)
        elif poll_backoff_seconds > 0:
            time.sleep(poll_backoff_seconds)

    raise TimeoutError(f"Session {id} did not settle before max_polls={max_polls}")


def run_session(
    client: Client,
    *,
    wait_for_seconds: int = 20,
    include_events: bool = True,
    timeout_seconds: typing.Optional[float] = None,
    poll_backoff_seconds: float = 0.0,
    max_polls: typing.Optional[int] = None,
    answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
    tools: typing.Optional[typing.Sequence[ToolInput]] = None,
    **create_params: typing_extensions.Unpack[CreateSessionParams],
) -> SessionRunResult[AnswerT]:
    """Create a session, then poll until it settles, running custom tools along the way.

    ``answer_schema`` binds a pydantic model as the agent's ``answer_format`` and
    validates the final answer back into it: ``result.answer`` is a model instance.
    """
    normalized_tools = as_tools(tools) if tools else []
    params: typing.Dict[str, typing.Any] = dict(create_params)
    if normalized_tools:
        _attach_tool_definitions(params, normalized_tools)
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
        tools=normalized_tools or None,
    )


async def _async_final_changes(
    client: AsyncClient, id: str, last_changes: typing.Optional[SessionChanges], limit: typing.Optional[int]
) -> typing.Optional[SessionChanges]:
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
    tools: typing.Optional[typing.Sequence[ToolInput]] = None,
) -> SessionRunResult[AnswerT]:
    """Async version of ``wait_for_session``."""
    tools_by_name = {t.name: t for t in as_tools(tools)} if tools else {}
    if tools_by_name and not include_events:
        raise ValueError("tools require include_events=True: pending calls arrive on the event stream.")
    answered: typing.Set[str] = set()
    advertised: typing.List[typing.Dict[str, typing.Any]] = []
    events: typing.List[SessionEvent] = []
    next_from_index = from_index
    last_changes: typing.Optional[SessionChanges] = None
    polls = 0
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while max_polls is None or polls < max_polls:
        polls += 1
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"Session {id} did not settle within {timeout_seconds}s")

        batch: typing.List[SessionEvent] = []
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
        if is_settled_session_status(status.status):
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

        if tools_by_name:
            advertised = _latest_pending_tool_calls(batch, advertised)
            # Status gate: on a replayed stream the live status decides whether calls are still open.
            if status.status == "awaiting_tool_results":
                if not advertised:
                    advertised = await _async_recover_pending_tool_calls(client, id)
                calls = [c for c in advertised if _call_key(c) not in answered]
                if calls:
                    results = [await _async_execute_tool_call(tools_by_name, c) for c in calls]
                    await _async_post_tool_results(client, id, results)
                    answered.update(_call_key(c) for c in calls)

        if not include_events:
            await asyncio.sleep(poll_backoff_seconds or wait_for_seconds)
        elif poll_backoff_seconds > 0:
            await asyncio.sleep(poll_backoff_seconds)

    raise TimeoutError(f"Session {id} did not settle before max_polls={max_polls}")


async def async_run_session(
    client: AsyncClient,
    *,
    wait_for_seconds: int = 20,
    include_events: bool = True,
    timeout_seconds: typing.Optional[float] = None,
    poll_backoff_seconds: float = 0.0,
    max_polls: typing.Optional[int] = None,
    answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
    tools: typing.Optional[typing.Sequence[ToolInput]] = None,
    **create_params: typing_extensions.Unpack[CreateSessionParams],
) -> SessionRunResult[AnswerT]:
    """Async version of ``run_session``."""
    normalized_tools = as_tools(tools) if tools else []
    params: typing.Dict[str, typing.Any] = dict(create_params)
    if normalized_tools:
        _attach_tool_definitions(params, normalized_tools)
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
        tools=normalized_tools or None,
    )


def stream_session(
    client: Client,
    id: str,
    *,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: typing.Optional[int] = None,
    until: typing_extensions.Literal["settled", "terminal"] = "settled",
    timeout_seconds: typing.Optional[float] = None,
) -> typing.Iterator[SessionEvent]:
    """Yield a session's events incrementally as they arrive, until it stops.

    Wraps the long-poll loop: each poll yields the events past the cursor, then the
    loop reads the authoritative status and stops per ``until`` (``"settled"`` =
    terminal or idle; ``"terminal"`` keeps the stream open across the idle turns of
    an interactive session). A final non-blocking drain loop flushes any backlog
    remaining when it stops. Unlike ``wait_for_session``, this does not execute
    custom tools: it is a read-only view of the event stream.

    Args:
        client: Client bound to the session.
        id: Session id to stream.
        from_index: Event index to start from; 0 replays the whole trajectory.
        wait_for_seconds: Server long-poll window per request.
        limit: Optional cap on events returned per poll.
        until: Stop on ``"settled"`` (terminal or idle) or only on ``"terminal"``.
        timeout_seconds: Optional overall wall-clock budget.

    Yields:
        Each new ``SessionEvent`` in order.

    Raises:
        TimeoutError: If ``timeout_seconds`` elapses before the session stops.
    """
    should_stop = is_terminal_session_status if until == "terminal" else is_settled_session_status
    next_from_index = from_index
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"Session {id} did not settle within {timeout_seconds}s")

        changes = client.sessions.get_session_changes(
            id, from_index=next_from_index, limit=limit, include_events=True, wait_for_seconds=wait_for_seconds
        )
        if changes is not None:
            batch = changes.new_events or []
            yield from batch
            next_from_index += len(batch)

        if should_stop(client.sessions.get_session_status(id).status):
            # Drain to exhaustion: one page may not cover the backlog past the cursor,
            # since the server caps page size (and honors ``limit``). Keep honoring the
            # wall-clock budget so a large tail cannot outlive ``timeout_seconds``.
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"Session {id} did not settle within {timeout_seconds}s")
                tail = client.sessions.get_session_changes(
                    id, from_index=next_from_index, limit=limit, include_events=True, wait_for_seconds=0
                )
                batch = tail.new_events or [] if tail is not None else []
                if not batch:
                    return
                yield from batch
                next_from_index += len(batch)


async def async_stream_session(
    client: AsyncClient,
    id: str,
    *,
    from_index: int = 0,
    wait_for_seconds: int = 20,
    limit: typing.Optional[int] = None,
    until: typing_extensions.Literal["settled", "terminal"] = "settled",
    timeout_seconds: typing.Optional[float] = None,
) -> typing.AsyncIterator[SessionEvent]:
    """Async version of ``stream_session``."""
    should_stop = is_terminal_session_status if until == "terminal" else is_settled_session_status
    next_from_index = from_index
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"Session {id} did not settle within {timeout_seconds}s")

        changes = await client.sessions.get_session_changes(
            id, from_index=next_from_index, limit=limit, include_events=True, wait_for_seconds=wait_for_seconds
        )
        if changes is not None:
            batch = changes.new_events or []
            for event in batch:
                yield event
            next_from_index += len(batch)

        status = await client.sessions.get_session_status(id)
        if should_stop(status.status):
            # Drain to exhaustion: one page may not cover the backlog past the cursor,
            # since the server caps page size (and honors ``limit``). Keep honoring the
            # wall-clock budget so a large tail cannot outlive ``timeout_seconds``.
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"Session {id} did not settle within {timeout_seconds}s")
                tail = await client.sessions.get_session_changes(
                    id, from_index=next_from_index, limit=limit, include_events=True, wait_for_seconds=0
                )
                batch = tail.new_events or [] if tail is not None else []
                if not batch:
                    return
                for event in batch:
                    yield event
                next_from_index += len(batch)


class SessionHandle(typing.Generic[AnswerT]):
    """A created session bound to its client: object-oriented sugar over the polling helpers."""

    def __init__(
        self,
        client: Client,
        id: str,
        answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
        tools: typing.Optional[typing.Sequence[ToolInput]] = None,
    ) -> None:
        self._client = client
        self._answer_schema = answer_schema
        self._tools = as_tools(tools) if tools else None
        self.id = id

    def get(self) -> Session:
        return self._client.sessions.get_session(self.id)

    def status(self) -> SessionStatus:
        return self._client.sessions.get_session_status(self.id)

    def changes(self, *, from_index: int = 0, **kwargs: typing.Any) -> typing.Optional[SessionChanges]:
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

    def wait_for_completion(self, **kwargs: typing.Any) -> SessionRunResult[AnswerT]:
        """Block until the session settles (terminal or idle); returns the result and final answer."""
        kwargs.setdefault("answer_schema", self._answer_schema)
        kwargs.setdefault("tools", self._tools)
        return wait_for_session(self._client, self.id, **kwargs)

    def stream(
        self,
        *,
        from_index: int = 0,
        wait_for_seconds: int = 20,
        limit: typing.Optional[int] = None,
        until: typing_extensions.Literal["settled", "terminal"] = "settled",
        timeout_seconds: typing.Optional[float] = None,
    ) -> typing.Iterator[SessionEvent]:
        """Yield this session's events live until it settles (terminal or idle)."""
        return stream_session(
            self._client,
            self.id,
            from_index=from_index,
            wait_for_seconds=wait_for_seconds,
            limit=limit,
            until=until,
            timeout_seconds=timeout_seconds,
        )


class AsyncSessionHandle(typing.Generic[AnswerT]):
    """Async version of :class:`SessionHandle`."""

    def __init__(
        self,
        client: AsyncClient,
        id: str,
        answer_schema: typing.Optional[typing.Type[AnswerT]] = None,
        tools: typing.Optional[typing.Sequence[ToolInput]] = None,
    ) -> None:
        self._client = client
        self._answer_schema = answer_schema
        self._tools = as_tools(tools) if tools else None
        self.id = id

    async def get(self) -> Session:
        return await self._client.sessions.get_session(self.id)

    async def status(self) -> SessionStatus:
        return await self._client.sessions.get_session_status(self.id)

    async def changes(self, *, from_index: int = 0, **kwargs: typing.Any) -> typing.Optional[SessionChanges]:
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

    async def wait_for_completion(self, **kwargs: typing.Any) -> SessionRunResult[AnswerT]:
        """Block until the session settles (terminal or idle); returns the result and final answer."""
        kwargs.setdefault("answer_schema", self._answer_schema)
        kwargs.setdefault("tools", self._tools)
        return await async_wait_for_session(self._client, self.id, **kwargs)

    def stream(
        self,
        *,
        from_index: int = 0,
        wait_for_seconds: int = 20,
        limit: typing.Optional[int] = None,
        until: typing_extensions.Literal["settled", "terminal"] = "settled",
        timeout_seconds: typing.Optional[float] = None,
    ) -> typing.AsyncIterator[SessionEvent]:
        """Yield this session's events live until it settles (terminal or idle)."""
        return async_stream_session(
            self._client,
            self.id,
            from_index=from_index,
            wait_for_seconds=wait_for_seconds,
            limit=limit,
            until=until,
            timeout_seconds=timeout_seconds,
        )

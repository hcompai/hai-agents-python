"""session: create, run, observe, and steer sessions."""

from __future__ import annotations

import time
import typing

import typer
from hai_agents import (
    SendSessionMessagesRequestBody_Batch,
    SendSessionMessagesRequestBody_UserMessage,
    is_terminal_session_status,
    run_session_until_done,
)
from rich.markdown import Markdown

from .. import views
from ..inputs import load_json
from ..state import AppState, confirm, get_client, get_state, safe

app = typer.Typer(no_args_is_help=True)


def _status_label(status: typing.Any) -> str:
    return str(getattr(status, "value", status))


def _create_params(
    agent: str,
    message: str | None,
    max_steps: int | None,
    max_time: float | None,
    idle_timeout: int | None,
    group_id: str | None,
    parent: str | None,
    answer_format: str | None,
) -> dict[str, typing.Any]:
    params: dict[str, typing.Any] = {"agent": agent}
    if message is not None:
        params["messages"] = message
    if max_steps is not None:
        params["max_steps"] = max_steps
    if max_time is not None:
        params["max_time_s"] = max_time
    if idle_timeout is not None:
        params["idle_timeout_s"] = idle_timeout
    if group_id is not None:
        params["group_id"] = group_id
    if parent is not None:
        params["parent_session_id"] = parent
    if answer_format is not None:
        params["answer_format"] = load_json(answer_format)
    return params


def _stream(
    state: AppState, client: typing.Any, session_id: str, from_index: int, wait_for_seconds: int, timeout: float | None
) -> typing.Any:
    """Tail a live session, printing events to stderr until it reaches a terminal status."""
    cursor = from_index
    last_changes = None
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"Session {session_id} did not finish within {timeout}s.")
        changes = client.sessions.get_session_changes(
            session_id, from_index=cursor, include_events=True, wait_for_seconds=wait_for_seconds
        )
        if changes is not None:
            last_changes = changes
            for event in changes.new_events or []:
                state.output.err.print(views.event_line(cursor, event))
                cursor += 1
        status = client.sessions.get_session_status(session_id)
        if is_terminal_session_status(status.status):
            return status, cursor, last_changes


def _final_answer(client: typing.Any, session_id: str, last_changes: typing.Any) -> typing.Any:
    if last_changes is not None and last_changes.answer is not None:
        return last_changes.answer
    fetched = client.sessions.get_session_changes(session_id, from_index=0, include_events=False, wait_for_seconds=0)
    return fetched.answer if fetched is not None else None


def _print_answer(state: AppState, answer: typing.Any) -> None:
    if answer is None:
        state.output.note("No answer produced.")
    elif isinstance(answer, str):
        state.output.out.print(Markdown(answer))
    else:
        state.output.print_json(answer)


@app.command("run")
@safe
def run(
    ctx: typer.Context,
    agent: str = typer.Option(..., "--agent", "-a", help="Agent name, e.g. h/web-surfer-holo3-1-35b."),
    message: str = typer.Option(None, "--message", "-m", help="Task for the agent."),
    max_steps: int = typer.Option(None, "--max-steps"),
    max_time: float = typer.Option(None, "--max-time", help="Max wall-clock seconds for the agent."),
    idle_timeout: int = typer.Option(None, "--idle-timeout", help="Keep the session idle for follow-ups."),
    group_id: str = typer.Option(None, "--group-id"),
    parent: str = typer.Option(None, "--parent", help="Parent session id."),
    answer_format: str = typer.Option(None, "--answer-format", help="JSON Schema (string, @path, or -)."),
    wait_for_seconds: int = typer.Option(20, "--wait", help="Long-poll window per request (max 25)."),
    timeout: float = typer.Option(None, "--timeout", help="Give up after this many seconds."),
) -> None:
    """Launch an agent and stream its progress until it finishes, then print the answer."""
    state = get_state(ctx)
    client = get_client(ctx)
    params = _create_params(agent, message, max_steps, max_time, idle_timeout, group_id, parent, answer_format)

    if state.output.json_mode:
        result = run_session_until_done(client, wait_for_seconds=wait_for_seconds, timeout_seconds=timeout, **params)
        state.output.print_json({"id": result.id, "status": result.status, "answer": result.answer})
        return

    session = client.sessions.create_session(**params)
    state.output.note(f"Session [bold]{session.id}[/bold] started.")
    status, _, last_changes = _stream(state, client, session.id, 0, wait_for_seconds, timeout)
    state.output.note(f"Finished: {_status_label(status.status)}")
    _print_answer(state, _final_answer(client, session.id, last_changes))


@app.command("create")
@safe
def create(
    ctx: typer.Context,
    agent: str = typer.Option(..., "--agent", "-a"),
    message: str = typer.Option(None, "--message", "-m"),
    max_steps: int = typer.Option(None, "--max-steps"),
    max_time: float = typer.Option(None, "--max-time"),
    idle_timeout: int = typer.Option(None, "--idle-timeout"),
    group_id: str = typer.Option(None, "--group-id"),
    parent: str = typer.Option(None, "--parent"),
    answer_format: str = typer.Option(None, "--answer-format"),
    idempotency_key: str = typer.Option(None, "--idempotency-key"),
) -> None:
    """Create a session without waiting for it to finish."""
    params = _create_params(agent, message, max_steps, max_time, idle_timeout, group_id, parent, answer_format)
    if idempotency_key is not None:
        params["idempotency_key"] = idempotency_key
    get_state(ctx).output.render(get_client(ctx).sessions.create_session(**params))


@app.command("tail")
@safe
def tail(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    from_index: int = typer.Option(0, "--from-index", help="Resume from this event index."),
    wait_for_seconds: int = typer.Option(20, "--wait"),
    timeout: float = typer.Option(None, "--timeout"),
) -> None:
    """Stream a running session's events until it reaches a terminal status."""
    state = get_state(ctx)
    client = get_client(ctx)
    if state.output.json_mode:
        changes = client.sessions.get_session_changes(
            session_id, from_index=from_index, include_events=True, wait_for_seconds=wait_for_seconds
        )
        state.output.print_json(changes)
        return
    status, _, _ = _stream(state, client, session_id, from_index, wait_for_seconds, timeout)
    state.output.note(f"Finished: {_status_label(status.status)}")


@app.command("status")
@safe
def status(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Show a session's live status snapshot."""
    get_state(ctx).output.render(get_client(ctx).sessions.get_session_status(session_id))


@app.command("get")
@safe
def get(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Fetch a full session."""
    get_state(ctx).output.render(get_client(ctx).sessions.get_session(session_id))


@app.command("list")
@safe
def list_(
    ctx: typer.Context,
    owner: str = typer.Option(None, "--owner", help="me | me-in-organization | organization | me-or-organization."),
    status: list[str] = typer.Option(None, "--status", help="Filter by status (repeatable)."),
    agent: list[str] = typer.Option(None, "--agent", help="Filter by agent (repeatable)."),
    group_id: str = typer.Option(None, "--group-id"),
    parent: str = typer.Option(None, "--parent"),
    search: str = typer.Option(None, "--search"),
    page: int = typer.Option(1, "--page"),
    size: int = typer.Option(10, "--size"),
) -> None:
    """List sessions visible to you."""
    result = get_client(ctx).sessions.list_sessions(
        owner=owner,
        status=list(status) if status else None,
        agent=list(agent) if agent else None,
        group_id=group_id,
        parent_session_id=parent,
        search=search,
        page=page,
        size=size,
    )
    get_state(ctx).output.render(result, views.sessions_table(result.items))


@app.command("events")
@safe
def events(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    type_: str = typer.Option(None, "--type", help="Filter by event type."),
    page: int = typer.Option(1, "--page"),
    size: int = typer.Option(50, "--size"),
) -> None:
    """Page through a session's event history."""
    result = get_client(ctx).sessions.list_session_events(session_id, type=type_, page=page, size=size)
    get_state(ctx).output.render(result, views.events_table(result.items))


@app.command("send")
@safe
def send(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent."),
    file: str = typer.Option(None, "--file", "-f", help="JSON batch body, @path, or - (overrides --message)."),
) -> None:
    """Send a message to steer a running session."""
    if file is not None:
        request = SendSessionMessagesRequestBody_Batch(**load_json(file))
    elif message is not None:
        request = SendSessionMessagesRequestBody_UserMessage(message=message)
    else:
        raise typer.BadParameter("provide --message or --file.")
    get_client(ctx).sessions.send_session_messages(session_id, request=request)
    get_state(ctx).output.note("Message sent.")


@app.command("pause")
@safe
def pause(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Pause a session, preserving its state."""
    get_client(ctx).sessions.pause_session(session_id)
    get_state(ctx).output.note("Paused.")


@app.command("resume")
@safe
def resume(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Resume a paused session."""
    get_client(ctx).sessions.resume_session(session_id)
    get_state(ctx).output.note("Resumed.")


@app.command("force-answer")
@safe
def force_answer(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Ask the agent to commit to a final answer on its next step."""
    get_client(ctx).sessions.force_session_answer(session_id)
    get_state(ctx).output.note("Force-answer requested.")


@app.command("cancel")
@safe
def cancel(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Cancel a session (it ends as interrupted)."""
    confirm(ctx, f"Cancel session '{session_id}'?")
    get_client(ctx).sessions.cancel_session(session_id)
    get_state(ctx).output.note("Cancellation requested.")


@app.command("feedback")
@safe
def feedback(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    success: bool = typer.Option(..., "--success/--fail", help="Whether the session succeeded."),
    message: str = typer.Option(None, "--message", "-m"),
) -> None:
    """Submit success feedback for a session."""
    get_client(ctx).sessions.submit_session_feedback(session_id, success=success, message=message)
    get_state(ctx).output.note("Feedback submitted.")


@app.command("event-feedback")
@safe
def event_feedback(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    event_index: int = typer.Argument(...),
    success: bool = typer.Option(..., "--success/--fail"),
    message: str = typer.Option(None, "--message", "-m"),
) -> None:
    """Submit feedback on a single event."""
    get_client(ctx).sessions.submit_event_feedback(session_id, event_index, success=success, message=message)
    get_state(ctx).output.note("Feedback submitted.")


@app.command("share")
@safe
def share(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Make a session publicly readable and print its share link."""
    get_state(ctx).output.render(get_client(ctx).sessions.share_session(session_id))


@app.command("unshare")
@safe
def unshare(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Revoke public access to a session."""
    get_client(ctx).sessions.unshare_session(session_id)
    get_state(ctx).output.note("Sharing revoked.")


@app.command("quota")
@safe
def quota(ctx: typer.Context) -> None:
    """Show the concurrent-session quota."""
    get_state(ctx).output.render(get_client(ctx).sessions.get_session_quota())

"""`hai` command-line interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import NoReturn

import click
import typer
from rich.console import Console
from rich.table import Table

from hai_agents import Client, run_session
from hai_agents.core.api_error import ApiError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.types import PageSessionSummary, SessionSummary

from ._client import absolute_share_url, make_client
from ._json import to_jsonable

H_GLYPH = "\n".join(
    (
        "| |  | |",
        "| |__| |",
        "|  __  |",
        "| |  | |",
        "|_|  |_|",
    )
)

DEFAULT_AGENT = "h/web-surfer-holo3-1-35b"

console = Console()

app = typer.Typer(
    name="hai",
    help="Run H Company agents from your terminal.",
    epilog=f'\b\n{H_GLYPH}\n\nExamples:\n  hai run "Find the H Agent API quickstart"\n'
    "  hai sessions share <session-id>",
    no_args_is_help=True,
    rich_markup_mode=None,
)
sessions_app = typer.Typer(no_args_is_help=True, help="Inspect and steer sessions.")


@dataclass(frozen=True)
class AppState:
    api_key: str | None
    base_url: str | None
    json_output: bool


@app.callback()
def configure(
    ctx: typer.Context,
    api_key: str | None = typer.Option(None, "--api-key", help="API key. Defaults to HAI_API_KEY or H_API_KEY."),
    base_url: str | None = typer.Option(None, "--base-url", help="Override the Agent Platform base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    ctx.obj = AppState(api_key=api_key, base_url=base_url, json_output=json_output)


@app.command()
def run(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task to run."),
    agent: str = typer.Option(DEFAULT_AGENT, "--agent", "-a", help="Registered agent name."),
    max_steps: int = typer.Option(20, "--max-steps", min=1, max=200, help="Maximum reasoning steps."),
    max_time_s: float = typer.Option(180.0, "--max-time", min=1.0, max=1800.0, help="Maximum run seconds."),
) -> None:
    """Run an agent task and print the final answer."""
    state = _state(ctx)
    client = _client(state)
    try:
        result = run_session(
            client,
            agent=agent,
            messages=task,
            max_steps=max_steps,
            max_time_s=max_time_s,
            timeout_seconds=max_time_s + 30.0,
        )
    except Exception as exc:
        _raise_cli_error(exc)
    _print_run_result(result, state.json_output)


@sessions_app.command("list")
def list_sessions(
    ctx: typer.Context,
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(10, "--size", min=1, max=100),
) -> None:
    """List visible sessions."""
    state = _state(ctx)
    client = _client(state)
    try:
        result: PageSessionSummary = client.sessions.list_sessions(page=page, size=size)
    except Exception as exc:
        _raise_cli_error(exc)

    if state.json_output:
        _print_json(result)
        return

    table = Table("ID", "Status", "Agent", "Created")
    for item in result.items:
        table.add_row(item.id, _status_text(item.status), item.agent or "", item.created_at.isoformat())
    console.print(table)


@sessions_app.command("get")
def get(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Fetch a full session envelope."""
    try:
        _print_json(_client(_state(ctx)).sessions.get_session(session_id))
    except Exception as exc:
        _raise_cli_error(exc)


@sessions_app.command("cancel")
def cancel(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Cancel a session."""
    state = _state(ctx)
    try:
        _client(state).sessions.cancel_session(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_ack("cancelled", state.json_output)


@sessions_app.command("send")
def send(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    message: str = typer.Argument(..., help="Message text to send."),
) -> None:
    """Send a follow-up message to a session."""
    state = _state(ctx)
    request = SendSessionMessagesRequestBody_UserMessage(message=message)
    try:
        _client(state).sessions.send_session_messages(session_id, request=request)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_ack("sent", state.json_output)


@sessions_app.command("share")
def share(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Create or fetch a public share URL."""
    state = _state(ctx)
    client = _client(state)
    try:
        share_url = absolute_share_url(client, client.sessions.share_session(session_id).share_url)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json({"share_url": share_url})
    else:
        console.print(share_url)


app.add_typer(sessions_app, name="sessions")


def main() -> None:
    app()


def _state(ctx: typer.Context) -> AppState:
    if not isinstance(ctx.obj, AppState):
        raise RuntimeError("CLI state was not initialized.")
    return ctx.obj


def _client(state: AppState) -> Client:
    try:
        return make_client(api_key=state.api_key, base_url=state.base_url)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _print_run_result(result, json_output: bool) -> None:
    payload = {
        "session_id": result.id,
        "status": _status_text(result.status),
        "answer": result.answer,
    }
    if json_output:
        _print_json(payload)
        return
    console.print(f"[bold]Session:[/bold] {result.id}")
    console.print(f"[bold]Status:[/bold] {_status_text(result.status)}")
    if result.answer is not None:
        console.print(result.answer)


def _print_ack(action: str, json_output: bool) -> None:
    if json_output:
        _print_json({"ack": True, "action": action})
    else:
        console.print(action)


def _print_json(value) -> None:
    console.print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))


def _status_text(status) -> str:
    return str(status)


def _raise_cli_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ApiError):
        body = exc.body
        message = body if isinstance(body, str) else json.dumps(to_jsonable(body), sort_keys=True)
        if exc.status_code is not None:
            message = f"API error {exc.status_code}: {message}"
        raise click.ClickException(message) from exc
    raise click.ClickException(str(exc)) from exc

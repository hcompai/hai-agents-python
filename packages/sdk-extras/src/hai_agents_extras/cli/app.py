"""`hai-agents` command-line interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from hai_agents_extras import runners
from hai_agents_extras._client import make_client
from hai_agents_extras._json import to_jsonable
from hai_agents_extras.mcp import server as mcp_server

H_GLYPH = "\n".join(
    (
        "| |  | |",
        "| |__| |",
        "|  __  |",
        "| |  | |",
        "|_|  |_|",
    )
)

DEFAULT_AGENT = runners.DEFAULT_AGENT

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="hai-agents",
    help="Run H Company agents from your terminal.",
    epilog=f'\b\n{H_GLYPH}\n\nExamples:\n  hai-agents run "Find the H Agent API quickstart"\n'
    "  hai-agents sessions share <session-id>\n  hai-agents mcp",
    no_args_is_help=True,
    rich_markup_mode=None,
)
sessions_app = typer.Typer(no_args_is_help=True, help="Inspect and steer sessions.")


@dataclass(frozen=True)
class AppState:
    api_key: Optional[str]
    base_url: Optional[str]
    json_output: bool


@app.callback()
def configure(
    ctx: typer.Context,
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key. Defaults to HAI_API_KEY or H_API_KEY."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Override the Agent Platform base URL."),
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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print streamed event names to stderr."),
) -> None:
    """Run an agent task and print the final answer."""
    state = _state(ctx)
    client = _client(state)
    params = runners.RunAgentParams(task=task, agent=agent, max_steps=max_steps, max_time_s=max_time_s)

    def on_event(event) -> None:
        if verbose:
            err_console.print(f"[dim]{event.type}[/dim]")

    result = runners.run_agent(client, params, on_event=on_event)
    _print_run_result(result, state.json_output)


@app.command()
def mcp(ctx: typer.Context) -> None:
    """Start the MCP stdio server."""
    state = _state(ctx)
    mcp_server.serve(api_key=state.api_key, base_url=state.base_url)


@sessions_app.command("list")
def list_sessions(
    ctx: typer.Context,
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(10, "--size", min=1, max=100),
) -> None:
    """List visible sessions."""
    state = _state(ctx)
    result = _client(state).sessions.list_sessions(page=page, size=size)
    if state.json_output:
        _print_json(result)
        return

    table = Table("ID", "Status", "Agent", "Created")
    for item in getattr(result, "items", []) or []:
        status = getattr(getattr(item, "status", None), "status", getattr(item, "status", ""))
        request = getattr(item, "request", None)
        agent = getattr(request, "agent", "") if request is not None else getattr(item, "agent", "")
        table.add_row(str(getattr(item, "id", "")), str(status), str(agent), str(getattr(item, "created_at", "")))
    console.print(table)


@sessions_app.command("get")
def get(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Fetch a full session envelope."""
    _print_json(runners.get_session(_client(_state(ctx)), session_id))


@sessions_app.command("cancel")
def cancel(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Cancel a session."""
    runners.cancel_session(_client(_state(ctx)), session_id)
    _print_ack("cancelled", _state(ctx).json_output)


@sessions_app.command("send")
def send(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    message: str = typer.Argument(..., help="Message text to send."),
) -> None:
    """Send a follow-up message to a session."""
    runners.send_message(_client(_state(ctx)), session_id, message)
    _print_ack("sent", _state(ctx).json_output)


@sessions_app.command("share")
def share(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Create or fetch a public share URL/path."""
    share_url = runners.share_session(_client(_state(ctx)), session_id)
    if _state(ctx).json_output:
        _print_json({"share_url": share_url})
    else:
        console.print(share_url)


app.add_typer(sessions_app, name="sessions")


def main() -> None:
    app()


def _state(ctx: typer.Context) -> AppState:
    return ctx.obj if isinstance(ctx.obj, AppState) else AppState(api_key=None, base_url=None, json_output=False)


def _client(state: AppState):
    try:
        return make_client(api_key=state.api_key, base_url=state.base_url)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _print_run_result(result, json_output: bool) -> None:
    status = str(getattr(result.status, "value", result.status))
    payload = {
        "session_id": result.id,
        "status": status,
        "answer": result.answer,
    }
    if json_output:
        _print_json(payload)
        return
    console.print(f"[bold]Session:[/bold] {result.id}")
    console.print(f"[bold]Status:[/bold] {status}")
    if result.answer is not None:
        console.print(result.answer)


def _print_ack(action: str, json_output: bool) -> None:
    if json_output:
        _print_json({"ack": True, "action": action})
    else:
        console.print(action)


def _print_json(value) -> None:
    console.print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))

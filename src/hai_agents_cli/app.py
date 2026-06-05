"""`hai` command-line interface."""

from __future__ import annotations

import json
import socket
import sys
from dataclasses import dataclass
from typing import NoReturn

import typer
from rich.console import Console
from rich.table import Table

from hai_agents import Client, run_session
from hai_agents.core.api_error import ApiError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.types import PageSessionSummary
from hai_agents_common import credentials
from hai_agents_common.credentials import absolute_share_url, make_client
from hai_agents_common.jsonable import to_jsonable

from . import auth
from .hosts import (
    CLIENTS,
    Status,
    host_present,
    host_target,
    unwire_mcp,
    unwire_skill,
    wire_mcp,
    wire_skill,
)
from .hosts import Client as HostClient

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
err_console = Console(stderr=True)

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
def login(
    force: bool = typer.Option(False, "--force", help="Re-authenticate and rotate the stored key."),
) -> None:
    """Sign in through the browser and store an API key in ~/.config/hai/.env."""
    if credentials.current_api_key() and not force:
        console.print("Already signed in. Pass --force to rotate the key.")
        return
    if not sys.stdin.isatty():
        _raise_cli_error(RuntimeError("login needs an interactive terminal and a browser."))

    label = f"hai CLI ({socket.gethostname()})"
    try:
        key = auth.login_and_mint(
            credentials.portal_base(),
            label,
            lambda url: console.print(f"Opening your browser. If it does not open, visit:\n  {url}", style="dim"),
        )
    except Exception as exc:
        _raise_cli_error(exc)
    path = credentials.save_api_key(key)
    console.print(f"Signed in. Wrote {credentials.API_KEY_VAR} to {path}.")


@app.command()
def logout() -> None:
    """Remove the stored API key from ~/.config/hai/.env."""
    path = credentials.clear_api_key()
    console.print(f"Removed {credentials.API_KEY_VAR} from {path}." if path else "No stored key found.")


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Show the resolved endpoint and authentication status."""
    state = _state(ctx)
    authenticated = credentials.current_api_key(state.api_key) is not None
    data = {
        "base_url": credentials.resolve_base_url(state.base_url),
        "authenticated": authenticated,
        "source": credentials.source(),
    }
    if state.json_output:
        _print_json(data)
        return
    table = Table("Field", "Value", show_header=False)
    table.add_row("Endpoint", data["base_url"] or "(SDK default)")
    table.add_row("Authenticated", "yes" if authenticated else "no")
    table.add_row("Key source", data["source"] or "(none)")
    console.print(table)


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
    client = _client(_state(ctx))
    try:
        result = client.sessions.get_session(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_json(result)


@sessions_app.command("cancel")
def cancel(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Cancel a session."""
    state = _state(ctx)
    if not yes and sys.stdin.isatty():
        typer.confirm(f"Cancel session {session_id}?", abort=True)
    client = _client(state)
    try:
        client.sessions.cancel_session(session_id)
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
    client = _client(state)
    request = SendSessionMessagesRequestBody_UserMessage(message=message)
    try:
        client.sessions.send_session_messages(session_id, request=request)
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
        print(share_url)


_STATUS_STYLE: dict[Status, tuple[str, str]] = {
    Status.INSTALLED: ("[bold green]+[/bold green]", "dim"),
    Status.REMOVED: ("[bold green]-[/bold green]", "dim"),
    Status.SKIPPED: ("[dim green].[/dim green]", "dim"),
    Status.ABSENT: ("[yellow]o[/yellow]", "yellow"),
    Status.FAILED: ("[bold red]x[/bold red]", "red"),
}
_ID_WIDTH = max(len(host_id) for host_id in CLIENTS)


@app.command()
def install(
    host: str = typer.Argument(None, help="Host id, 'list' to enumerate, or omit to wire all detected."),
) -> None:
    """Wire the hai MCP server (and a delegation skill) into MCP hosts like Cursor or Claude Code."""
    if host == "list":
        _list_hosts()
        return
    _apply_hosts(host, wire_mcp, wire_skill, verb="install")


@app.command()
def uninstall(
    host: str = typer.Argument(None, help="Host id, or omit to remove from all detected."),
) -> None:
    """Remove the hai MCP server and delegation skill from MCP hosts."""
    _apply_hosts(host, unwire_mcp, unwire_skill, verb="uninstall")


def _list_hosts() -> None:
    console.print()
    for host_id, c in CLIENTS.items():
        glyph = "[green]+[/green]" if host_present(c) else "[dim].[/dim]"
        console.print(f"  {glyph} [bold cyan]{host_id:<{_ID_WIDTH}}[/bold cyan]  [dim]{host_target(c)}[/dim]")
    console.print("\n  [dim]+ = detected; wire with[/dim] [cyan]hai install <id>[/cyan]\n")


def _resolve_targets(host: str | None) -> list[tuple[str, HostClient]]:
    if host is None:
        targets = [(host_id, c) for host_id, c in CLIENTS.items() if host_present(c)]
        if not targets:
            err_console.print("[yellow]No supported hosts detected.[/yellow] Try [cyan]hai install list[/cyan].")
            raise typer.Exit(1)
        return targets
    if host in CLIENTS:
        return [(host, CLIENTS[host])]
    err_console.print(f"[red]Error:[/red] unknown host {host!r}. Try [cyan]hai install list[/cyan].")
    raise typer.Exit(2)


def _apply_hosts(host: str | None, mcp_fn, skill_fn, verb: str) -> None:
    targets = _resolve_targets(host)
    console.print()
    failed = False
    for host_id, c in targets:
        status, detail = mcp_fn(c)
        glyph, color = _STATUS_STYLE[status]
        line = f"  {glyph} [bold cyan]{host_id:<{_ID_WIDTH}}[/bold cyan]  [{color}]{detail}[/{color}]"
        skill_fatal = False
        if c.skills_dir is not None:
            s_status, s_detail = skill_fn(c)
            skill_fatal = s_status.fatal
            if s_status.ok:
                line += f"  [dim]-> {s_detail}[/dim]"
            else:
                s_glyph, s_color = _STATUS_STYLE[s_status]
                line += f"  {s_glyph} [{s_color}]{s_detail}[/{s_color}]"
        console.print(line)
        failed |= status.fatal or skill_fatal
    console.print()
    if failed:
        raise typer.Exit(1)


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
        _raise_cli_error(exc)


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
    # Emit raw JSON to stdout; rich's Console would soft-wrap and corrupt long values.
    print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))


def _status_text(status) -> str:
    return str(status)


def _raise_cli_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ApiError):
        body = exc.body
        message = body if isinstance(body, str) else json.dumps(to_jsonable(body), sort_keys=True)
        if exc.status_code is not None:
            message = f"API error {exc.status_code}: {message}"
    else:
        message = str(exc)
    err_console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)

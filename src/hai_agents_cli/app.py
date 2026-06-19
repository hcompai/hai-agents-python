"""`hai` command-line interface."""

from __future__ import annotations

import json
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from hai_agents import Client, assert_request_under_limit, is_settled_session_status, wait_for_session
from hai_agents.core.api_error import ApiError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.types import PageSessionSummary
from hai_agents_common import credentials
from hai_agents_common.credentials import absolute_share_url, make_client
from hai_agents_common.jsonable import to_jsonable

from . import auth, mcp_hosts

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
agents_app = typer.Typer(no_args_is_help=True, help="Browse available agents.")
skills_app = typer.Typer(no_args_is_help=True, help="Browse available skills.")
mcp_app = typer.Typer(no_args_is_help=True, help="Manage the hai-agents MCP server.")


@dataclass(frozen=True)
class AppState:
    api_key: str | None
    base_url: str | None
    json_output: bool


@app.callback()
def configure(
    ctx: typer.Context,
    api_key: str | None = typer.Option(None, "--api-key", help="API key. Defaults to HAI_API_KEY."),
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
        "source": credentials.source(state.api_key),
    }
    if state.json_output:
        _print_json(data)
        return
    table = Table("Field", "Value", show_header=False)
    table.add_row("Endpoint", data["base_url"] or "(SDK default)")
    table.add_row("Authenticated", "yes" if authenticated else "no")
    table.add_row("Key source", data["source"] or "(none)")
    console.print(table)


def _parse_overrides(items: list[str]) -> dict[str, Any]:
    """Parse repeated ``PATH=VALUE`` flags into an overrides dict.

    The separating ``=`` is the first one outside ``[...]``, since selector
    clauses like ``[kind=web]`` carry their own ``=``. VALUE is read as JSON,
    falling back to a plain string when it is not valid JSON.
    """
    overrides: dict[str, Any] = {}
    for item in items:
        depth = 0
        cut = None
        for i, char in enumerate(item):
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            elif char == "=" and depth == 0:
                cut = i
                break
        if cut is None:
            raise typer.BadParameter(f"override must be PATH=VALUE: {item!r}")
        path, raw = item[:cut], item[cut + 1 :]
        try:
            overrides[path] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[path] = raw
    return overrides


@app.command()
def run(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task to run."),
    agent: str = typer.Option(DEFAULT_AGENT, "--agent", "-a", help="Registered agent name."),
    max_steps: int = typer.Option(20, "--max-steps", min=1, max=200, help="Maximum reasoning steps."),
    max_time_s: float = typer.Option(180.0, "--max-time", min=1.0, max=1800.0, help="Maximum run seconds."),
    override: list[str] = typer.Option(
        None,
        "--override",
        "-o",
        help=(
            "Per-run override as PATH=VALUE, repeatable. VALUE is parsed as JSON, else a string. "
            "Example: -o 'agent.environments[kind=web].start_url=https://bing.com'"
        ),
    ),
) -> None:
    """Run an agent task and print the final answer."""
    state = _state(ctx)
    client = _client(state)
    overrides = _parse_overrides(override or [])
    params: dict[str, Any] = {
        "agent": agent,
        "messages": task,
        "max_steps": max_steps,
        "max_time_s": max_time_s,
    }
    if overrides:
        params["overrides"] = overrides
    try:
        assert_request_under_limit(params)
        session = client.sessions.create_session(**params)
    except Exception as exc:
        _raise_cli_error(exc)
    agent_view_url = getattr(session, "agent_view_url", None)
    if agent_view_url and not state.json_output:
        console.print(f"[bold]Live view:[/bold] [link={agent_view_url}]{agent_view_url}[/link]")
    try:
        result = wait_for_session(client, session.id, timeout_seconds=max_time_s + 30.0)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_run_result(result, state.json_output, agent_view_url=agent_view_url)


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
        url = getattr(item, "agent_view_url", None)
        id_cell = f"[link={url}]{item.id}[/link]" if url else item.id
        table.add_row(id_cell, _status_text(item.status), item.agent or "", item.created_at.isoformat())
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
        current = client.sessions.get_session_status(session_id)
        if is_settled_session_status(current.status):
            if state.json_output:
                _print_json({"ack": False, "action": "cancel", "status": _status_text(current.status)})
            else:
                console.print(f"Session already {_status_text(current.status)}; nothing to cancel.")
            return
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


@sessions_app.command("unshare")
def unshare(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Revoke a session's public share URL."""
    state = _state(ctx)
    client = _client(state)
    try:
        client.sessions.unshare_session(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_ack("unshared", state.json_output)


@sessions_app.command("status")
def status(ctx: typer.Context, session_id: str = typer.Argument(...)) -> None:
    """Show a session's live status, step count, and error if any."""
    state = _state(ctx)
    client = _client(state)
    try:
        result = client.sessions.get_session_status(session_id)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json(result)
        return
    table = Table("Field", "Value", show_header=False)
    table.add_row("Status", _status_text(result.status))
    if result.steps is not None:
        table.add_row("Steps", str(result.steps))
    if result.error:
        table.add_row("Error", result.error)
    console.print(table)


@sessions_app.command("events")
def events(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    from_index: int = typer.Option(0, "--from-index", min=0, help="Skip events before this index."),
    wait: int = typer.Option(0, "--wait", min=0, max=60, help="Long-poll up to N seconds for new events."),
) -> None:
    """Print a session's trajectory events from an index."""
    state = _state(ctx)
    client = _client(state)
    try:
        changes = client.sessions.get_session_changes(
            session_id, from_index=from_index, include_events=True, wait_for_seconds=wait
        )
    except Exception as exc:
        _raise_cli_error(exc)
    new_events = (changes.new_events if changes else None) or []
    if state.json_output:
        _print_json(new_events)
        return
    if not new_events:
        console.print("[dim]No new events.[/dim]")
        return
    for offset, event in enumerate(new_events):
        console.print(_event_line(from_index + offset, event))


@sessions_app.command("watch")
def watch(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    timeout: float = typer.Option(300.0, "--timeout", min=1.0, help="Stop watching after N seconds."),
) -> None:
    """Stream a session's events live until it settles."""
    state = _state(ctx)
    client = _client(state)
    from_index = 0
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _raise_cli_error(TimeoutError(f"Session {session_id} did not settle within {timeout}s."))
        try:
            changes = client.sessions.get_session_changes(
                session_id,
                from_index=from_index,
                include_events=True,
                wait_for_seconds=max(1, min(20, int(remaining))),
            )
            for event in (changes.new_events if changes else None) or []:
                _emit_watch_event(state, from_index, event)
                from_index += 1
            current = client.sessions.get_session_status(session_id)
            if is_settled_session_status(current.status):
                # /changes is a delta endpoint: drain events that landed between the last poll
                # and settling, otherwise the tail of the trajectory is silently dropped.
                tail = client.sessions.get_session_changes(
                    session_id, from_index=from_index, include_events=True, wait_for_seconds=0
                )
                for event in (tail.new_events if tail else None) or []:
                    _emit_watch_event(state, from_index, event)
                    from_index += 1
                # The terminal answer lives on /changes, not /status.
                final = client.sessions.get_session_changes(
                    session_id, from_index=0, include_events=False, wait_for_seconds=0
                )
                _print_watch_result(state, current, final)
                return
        except Exception as exc:
            _raise_cli_error(exc)


@agents_app.command("list")
def list_agents_command(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search", help="Match on agent name or description."),
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(20, "--size", min=1, max=100),
) -> None:
    """List reserved and org agents."""
    state = _state(ctx)
    client = _client(state)
    try:
        result = client.agents.list_agents(search=search, page=page, size=size)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json(result)
        return
    table = Table("Name", "Description")
    for item in result.items:
        table.add_row(item.name, _truncate(item.description))
    console.print(table)


@agents_app.command("get")
def get_agent_command(
    ctx: typer.Context,
    agent_name: str = typer.Argument(...),
    resolve: bool = typer.Option(False, "--resolve", help="Resolve inherited fields."),
) -> None:
    """Fetch a single agent definition."""
    client = _client(_state(ctx))
    try:
        result = client.agents.get_agent(agent_name, resolve=resolve)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_json(result)


@skills_app.command("list")
def list_skills_command(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search", help="Match on skill name or description."),
    page: int = typer.Option(1, "--page", min=1),
    size: int = typer.Option(20, "--size", min=1, max=100),
) -> None:
    """List available skills."""
    state = _state(ctx)
    client = _client(state)
    try:
        result = client.skills.list_skills(search=search, page=page, size=size)
    except Exception as exc:
        _raise_cli_error(exc)
    if state.json_output:
        _print_json(result)
        return
    table = Table("Name", "Description")
    for item in result.items:
        table.add_row(item.name, _truncate(item.description))
    console.print(table)


@skills_app.command("get")
def get_skill_command(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    """Fetch a single skill definition."""
    client = _client(_state(ctx))
    try:
        result = client.skills.get_skill(name)
    except Exception as exc:
        _raise_cli_error(exc)
    _print_json(result)


@mcp_app.command("install")
def mcp_install(
    ctx: typer.Context,
    client: str = typer.Argument(
        None, help="Client id (cursor, vscode, ...), 'list' to enumerate, or omit to wire every detected client."
    ),
    url: str = typer.Option(None, "--url", help="MCP endpoint. Defaults to your --base-url region or the EU host."),
) -> None:
    """Wire the hai-agents MCP server into local clients (writes your API key into each config in plaintext)."""
    state = _state(ctx)
    if client == "list":
        _mcp_list(state.json_output)
        return

    if client is None:
        targets = [(cid, c) for cid, c in mcp_hosts.CLIENTS.items() if mcp_hosts.host_present(c)]
        if not targets:
            _raise_cli_error(RuntimeError("No supported MCP clients detected. Run `hai mcp install list`."))
    elif client in mcp_hosts.CLIENTS:
        targets = [(client, mcp_hosts.CLIENTS[client])]
    else:
        _raise_cli_error(RuntimeError(f"Unknown client {client!r}. Run `hai mcp install list` to see supported ids."))

    try:
        resolved = credentials.resolve_api_key(state.api_key)
        key = resolved() if callable(resolved) else resolved
    except RuntimeError as exc:
        _raise_cli_error(exc)
    server_url = mcp_hosts.resolve_mcp_url(credentials.resolve_base_url(state.base_url), url)

    results = [_install_one(cid, c, server_url, key) for cid, c in targets]
    _print_mcp_results(results, server_url, state.json_output)
    if any(r["status"].fatal or (r["skill"] and r["skill"][0].fatal) for r in results):
        raise typer.Exit(1)


def _install_one(cid: str, c: mcp_hosts.Client, url: str, key: str) -> dict:
    status, detail = mcp_hosts.wire_mcp(c, url, key)
    skill = mcp_hosts.wire_skill(c) if c.skills_dir is not None else None
    return {"client": cid, "status": status, "detail": detail, "skill": skill}


def _mcp_list(json_output: bool) -> None:
    rows = [(cid, mcp_hosts.host_present(c), mcp_hosts.host_target(c)) for cid, c in mcp_hosts.CLIENTS.items()]
    if json_output:
        _print_json({cid: {"detected": detected, "target": tgt} for cid, detected, tgt in rows})
        return
    table = Table("Client", "Detected", "Config")
    for cid, detected, tgt in rows:
        table.add_row(cid, "[green]yes[/green]" if detected else "[dim]no[/dim]", tgt)
    console.print(table)
    console.print(
        "[dim]Wire one with[/dim] [cyan]hai mcp install <id>[/cyan][dim], or all detected with[/dim] [cyan]hai mcp install[/cyan]."
    )


_MCP_GLYPH: dict[mcp_hosts.Status, str] = {
    mcp_hosts.Status.INSTALLED: "[bold green]+[/bold green]",
    mcp_hosts.Status.SKIPPED: "[dim green]=[/dim green]",
    mcp_hosts.Status.ABSENT: "[yellow]-[/yellow]",
    mcp_hosts.Status.FAILED: "[bold red]x[/bold red]",
}


def _print_mcp_results(results: list[dict], server_url: str, json_output: bool) -> None:
    if json_output:
        _print_json(
            {
                "url": server_url,
                "results": [
                    {
                        "client": r["client"],
                        "status": r["status"].value,
                        "detail": r["detail"],
                        "skill": ({"status": r["skill"][0].value, "detail": r["skill"][1]} if r["skill"] else None),
                    }
                    for r in results
                ],
            }
        )
        return
    for r in results:
        line = f"  {_MCP_GLYPH[r['status']]} [bold cyan]{r['client']}[/bold cyan]  {r['detail']}"
        if r["skill"] and r["skill"][0].ok:
            line += f"  [dim]+ skill {r['skill'][1]}[/dim]"
        elif r["skill"]:
            line += f"  {_MCP_GLYPH[r['skill'][0]]} [dim]skill: {r['skill'][1]}[/dim]"
        console.print(line)
    console.print(f"\n[bold]Server:[/bold] {server_url}")
    console.print("[yellow]Your API key was written into these configs in plaintext. Keep them private.[/yellow]")


app.add_typer(sessions_app, name="sessions")
app.add_typer(agents_app, name="agents")
app.add_typer(skills_app, name="skills")
app.add_typer(mcp_app, name="mcp")


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


def _print_run_result(result, json_output: bool, agent_view_url: str | None = None) -> None:
    payload = {
        "session_id": result.id,
        "status": _status_text(result.status),
        "answer": result.answer,
        "agent_view_url": agent_view_url,
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


def _print_watch_result(state: AppState, status_result, final) -> None:
    if state.json_output:
        print(json.dumps(to_jsonable(final if final is not None else status_result), sort_keys=True))
        return
    console.print(f"[bold]Status:[/bold] {_status_text(status_result.status)}")
    error = status_result.error or (final.error if final is not None else None)
    if error:
        console.print(f"[bold]Error:[/bold] {error}")
    answer = final.answer if final is not None else None
    if answer is not None:
        console.print(answer)


def _status_text(status) -> str:
    return str(status)


def _truncate(text: str | None, limit: int = 80) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _event_line(index: int, event) -> str:
    event_type = getattr(event, "type", "Event")
    data = getattr(event, "data", None)
    detail = _truncate(json.dumps(to_jsonable(data), sort_keys=True), 120) if data is not None else ""
    return f"[dim]{index:>4}[/dim] [cyan]{event_type}[/cyan]" + (f"  {detail}" if detail else "")


def _emit_watch_event(state: AppState, index: int, event) -> None:
    if state.json_output:
        print(json.dumps(to_jsonable(event), sort_keys=True))
    else:
        console.print(_event_line(index, event))


def _format_api_body(body) -> str:
    """Human-readable message from an API error body, flattening 422 validation detail."""
    if isinstance(body, str):
        return body
    detail = getattr(body, "detail", None)
    if detail is None and isinstance(body, dict):
        detail = body.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            loc = getattr(item, "loc", None) if not isinstance(item, dict) else item.get("loc")
            msg = getattr(item, "msg", None) if not isinstance(item, dict) else item.get("msg")
            if msg:
                where = ".".join(str(p) for p in loc) if loc else ""
                parts.append(f"{where}: {msg}" if where else str(msg))
        if parts:
            return "; ".join(parts)
    return json.dumps(to_jsonable(body), sort_keys=True)


def _raise_cli_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ApiError):
        message = _format_api_body(exc.body)
        if exc.status_code is not None:
            message = f"API error {exc.status_code}: {message}"
    else:
        message = str(exc)
    err_console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)

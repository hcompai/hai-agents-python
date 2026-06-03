"""agent: manage agents."""

from __future__ import annotations

import typer

from .. import views
from ..inputs import load_json
from ..state import confirm, get_client, get_state, safe

app = typer.Typer(no_args_is_help=True)


@app.command("list")
@safe
def list_(
    ctx: typer.Context,
    search: str = typer.Option(None, "--search", help="Match on name or description."),
    page: int = typer.Option(1, "--page"),
    size: int = typer.Option(10, "--size"),
) -> None:
    """List reserved and org agents."""
    result = get_client(ctx).agents.list_agents(search=search, page=page, size=size)
    get_state(ctx).output.render(result, views.agents_table(result.items))


@app.command("get")
@safe
def get(ctx: typer.Context, name: str = typer.Argument(..., help="Agent name, e.g. h/web-surfer-holo3-1-35b.")) -> None:
    """Fetch a single agent."""
    get_state(ctx).output.render(get_client(ctx).agents.get_agent(name))


@app.command("create")
@safe
def create(
    ctx: typer.Context,
    name: str = typer.Option(None, "--name"),
    description: str = typer.Option(None, "--description"),
    environment: list[str] = typer.Option(None, "--environment", "-e", help="Environment id (repeatable)."),
    model: str = typer.Option(None, "--model"),
    instructions: str = typer.Option(None, "--instructions"),
    subagent: list[str] = typer.Option(None, "--subagent", help="Subagent name (repeatable)."),
    skill: list[str] = typer.Option(None, "--skill", help="Skill name (repeatable)."),
    file: str = typer.Option(None, "--file", "-f", help="JSON body, @path, or - for stdin (overrides flags)."),
) -> None:
    """Create an agent from flags or a JSON body."""
    if file is not None:
        body = load_json(file)
    else:
        if not name or not description or not environment:
            raise typer.BadParameter("--name, --description, and at least one --environment are required.")
        body = {"name": name, "description": description, "environments": environment}
        if model:
            body["model"] = model
        if instructions:
            body["instructions"] = instructions
        if subagent:
            body["subagents"] = list(subagent)
        if skill:
            body["skills"] = list(skill)
    get_state(ctx).output.render(get_client(ctx).agents.create_agent(**body))


@app.command("update")
@safe
def update(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Agent name to replace."),
    file: str = typer.Option(..., "--file", "-f", help="JSON body, @path, or - for stdin."),
) -> None:
    """Replace an agent's definition (no rename)."""
    get_state(ctx).output.render(get_client(ctx).agents.update_agent(name, **load_json(file)))


@app.command("delete")
@safe
def delete(ctx: typer.Context, name: str = typer.Argument(..., help="Agent name to delete.")) -> None:
    """Delete an agent."""
    confirm(ctx, f"Delete agent '{name}'?")
    get_client(ctx).agents.delete_agent(name)
    get_state(ctx).output.note(f"Deleted agent '{name}'.")

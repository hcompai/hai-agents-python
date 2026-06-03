"""env: manage environments (currently the web/browser kind)."""

from __future__ import annotations

import typer
from hai_agents import CreateEnvironmentRequest_Web, UpdateEnvironmentRequestBody_Web

from .. import views
from ..inputs import load_json
from ..state import confirm, get_client, get_state, safe

app = typer.Typer(no_args_is_help=True)


@app.command("list")
@safe
def list_(
    ctx: typer.Context,
    kind: str = typer.Option(None, "--kind", help="Filter by kind, e.g. web."),
    search: str = typer.Option(None, "--search"),
    page: int = typer.Option(1, "--page"),
    size: int = typer.Option(10, "--size"),
) -> None:
    """List reserved and org environments."""
    result = get_client(ctx).environments.list_environments(kind=kind, search=search, page=page, size=size)
    get_state(ctx).output.render(result, views.environments_table(result.items))


@app.command("get")
@safe
def get(ctx: typer.Context, env_id: str = typer.Argument(..., help="Environment id.")) -> None:
    """Fetch a single environment."""
    get_state(ctx).output.render(get_client(ctx).environments.get_environment(env_id))


@app.command("create")
@safe
def create(
    ctx: typer.Context,
    env_id: str = typer.Option(None, "--id", help="Environment id to create."),
    headless: bool = typer.Option(True, "--headless/--headed"),
    width: int = typer.Option(1280, "--width"),
    height: int = typer.Option(720, "--height"),
    start_url: str = typer.Option(None, "--start-url"),
    mode: str = typer.Option(None, "--mode", help="visual (default), text, or multimodal."),
    file: str = typer.Option(None, "--file", "-f", help="JSON body, @path, or - (overrides flags)."),
) -> None:
    """Create a web/browser environment."""
    if file is not None:
        request = CreateEnvironmentRequest_Web(**load_json(file))
    else:
        if not env_id:
            raise typer.BadParameter("--id is required.")
        request = CreateEnvironmentRequest_Web(
            id=env_id, headless=headless, width=width, height=height, start_url=start_url, mode=mode
        )
    get_state(ctx).output.render(get_client(ctx).environments.create_environment(request=request))


@app.command("update")
@safe
def update(
    ctx: typer.Context,
    env_id: str = typer.Argument(..., help="Environment id to replace."),
    file: str = typer.Option(..., "--file", "-f", help="JSON body, @path, or - for stdin."),
) -> None:
    """Replace an environment's definition."""
    request = UpdateEnvironmentRequestBody_Web(**load_json(file))
    get_state(ctx).output.render(get_client(ctx).environments.update_environment(env_id, request=request))


@app.command("delete")
@safe
def delete(ctx: typer.Context, env_id: str = typer.Argument(..., help="Environment id to delete.")) -> None:
    """Delete an environment."""
    confirm(ctx, f"Delete environment '{env_id}'?")
    get_client(ctx).environments.delete_environment(env_id)
    get_state(ctx).output.note(f"Deleted environment '{env_id}'.")

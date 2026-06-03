"""skill: manage skills."""

from __future__ import annotations

from pathlib import Path

import typer

from .. import views
from ..inputs import load_json
from ..state import confirm, get_client, get_state, safe

app = typer.Typer(no_args_is_help=True)


@app.command("list")
@safe
def list_(
    ctx: typer.Context,
    name: str = typer.Option(None, "--name", help="Substring match on name."),
    search: str = typer.Option(None, "--search", help="Match on name or description."),
    page: int = typer.Option(1, "--page"),
    size: int = typer.Option(10, "--size"),
) -> None:
    """List reserved and org skills."""
    result = get_client(ctx).skills.list_skills(name=name, search=search, page=page, size=size)
    get_state(ctx).output.render(result, views.skills_table(result.items))


@app.command("get")
@safe
def get(ctx: typer.Context, name: str = typer.Argument(..., help="Skill name.")) -> None:
    """Fetch a single skill."""
    get_state(ctx).output.render(get_client(ctx).skills.get_skill(name))


@app.command("create")
@safe
def create(
    ctx: typer.Context,
    name: str = typer.Option(None, "--name"),
    description: str = typer.Option(None, "--description"),
    body: str = typer.Option(None, "--body", help="Markdown body."),
    body_file: str = typer.Option(None, "--body-file", help="Read the markdown body from a file."),
    source: str = typer.Option(None, "--source"),
    url_pattern: str = typer.Option(None, "--url-pattern"),
    file: str = typer.Option(None, "--file", "-f", help="JSON body, @path, or - (overrides flags)."),
) -> None:
    """Create a skill from flags or a JSON body."""
    if file is not None:
        payload = load_json(file)
    else:
        content = Path(body_file).read_text(encoding="utf-8") if body_file else body
        if not name or not description or not content:
            raise typer.BadParameter("--name, --description, and --body/--body-file are required.")
        payload = {"name": name, "description": description, "body": content}
        if source:
            payload["source"] = source
        if url_pattern:
            payload["url_pattern"] = url_pattern
    get_state(ctx).output.render(get_client(ctx).skills.create_skill(**payload))


@app.command("update")
@safe
def update(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Skill name to replace."),
    file: str = typer.Option(..., "--file", "-f", help="JSON body, @path, or - for stdin."),
) -> None:
    """Replace a skill's content (no rename)."""
    get_state(ctx).output.render(get_client(ctx).skills.update_skill(name, **load_json(file)))


@app.command("delete")
@safe
def delete(ctx: typer.Context, name: str = typer.Argument(..., help="Skill name to delete.")) -> None:
    """Delete a skill."""
    confirm(ctx, f"Delete skill '{name}'?")
    get_client(ctx).skills.delete_skill(name)
    get_state(ctx).output.note(f"Deleted skill '{name}'.")

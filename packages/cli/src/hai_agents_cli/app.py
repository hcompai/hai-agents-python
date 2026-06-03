"""``hai`` - the command-line interface for the H Company Agent API."""

from __future__ import annotations

import json
import os
import sys

import typer
from typer.main import get_command

from . import config as config_module
from .commands import agent, environment, session, skill
from .output import Output, OutputMode
from .schema import describe
from .state import AppState, get_state

app = typer.Typer(
    name="hai",
    help="Launch and steer H Company agents from your terminal.",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
)

app.add_typer(session.app, name="session", help="Create, run, and steer sessions.")
app.add_typer(agent.app, name="agent", help="Manage agents.")
app.add_typer(skill.app, name="skill", help="Manage skills.")
app.add_typer(environment.app, name="env", help="Manage environments.")


@app.callback()
def main(
    ctx: typer.Context,
    output: OutputMode = typer.Option(
        OutputMode.AUTO, "--output", "-o", help="Output format. 'auto' uses tables on a TTY, JSON when piped."
    ),
    region: str = typer.Option(None, "--region", help="API region: eu (default) or us.", envvar="H_REGION"),
    base_url: str = typer.Option(None, "--base-url", help="Override the API base URL.", envvar="H_BASE_URL"),
    token: str = typer.Option(None, "--token", help="API key.", envvar="H_API_KEY"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress and notes on stderr."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable ANSI colors."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
    no_input: bool = typer.Option(False, "--no-input", help="Never prompt; fail instead of asking."),
) -> None:
    ctx.obj = AppState(
        output=Output.create(output, quiet=quiet, no_color=no_color),
        config=config_module.resolve(token=token, region=region, base_url=base_url),
        assume_yes=assume_yes,
        no_input=no_input,
    )


@app.command()
def schema() -> None:
    """Print a machine-readable JSON description of every command (for agents and tooling)."""
    print(json.dumps(describe(get_command(app), "hai"), indent=2))


@app.command()
def configure(
    ctx: typer.Context,
    token: str = typer.Option(..., "--token", prompt=True, hide_input=True, help="API key to store."),
    region: str = typer.Option(config_module.DEFAULT_REGION, "--region", help="Default region: eu or us."),
    base_url: str = typer.Option(None, "--base-url", help="Optional base URL override."),
) -> None:
    """Save credentials to the config file (~/.config/hai/config.toml)."""
    path = config_module.save(token=token, region=region, base_url=base_url)
    get_state(ctx).output.note(f"Saved configuration to [bold]{path}[/bold].")


def run() -> None:
    try:
        app()
    except BrokenPipeError:
        # A downstream reader (e.g. `| head`) closed the pipe. Silence the flush
        # error on interpreter shutdown by pointing stdout at the void, then exit.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()

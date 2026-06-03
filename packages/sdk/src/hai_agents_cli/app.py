"""``hai`` - the command-line interface for the H Company Agent API."""

from __future__ import annotations

import importlib.metadata
import json
import os
import socket
import sys

import typer
from typer.main import get_command

from . import auth
from . import client as client_module
from . import config as config_module
from .commands import agent, environment, session, skill
from .output import Output, OutputMode
from .schema import describe
from .state import AppState, get_state
from .views import kv_table

_EPILOG = """\
[bold]Examples[/bold]
  hai login
  hai session run -a h/web-surfer-holo3-1-35b -m "Top 3 Hacker News stories?"
  hai session list -o json | jq '.items[].id'
"""

app = typer.Typer(
    name="hai",
    help="Launch and steer H Company agents from your terminal.",
    epilog=_EPILOG,
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        try:
            version = importlib.metadata.version("hai-agents")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        print(f"hai {version}")
        raise typer.Exit()


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
    region: str = typer.Option(None, "--region", help="API region: eu (default) or us.", envvar="HAI_REGION"),
    base_url: str = typer.Option(None, "--base-url", help="Override the API base URL.", envvar="HAI_BASE_URL"),
    token: str = typer.Option(None, "--token", help="API key.", envvar="HAI_API_KEY"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress and notes on stderr."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable ANSI colors."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
    no_input: bool = typer.Option(False, "--no-input", help="Never prompt; fail instead of asking."),
    version: bool = typer.Option(
        None, "--version", "-V", callback=_version_callback, is_eager=True, help="Show the version and exit."
    ),
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
def login(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Re-authenticate and rotate the stored key."),
) -> None:
    """Sign in via the browser and write a fresh API key to a local .env."""
    state = get_state(ctx)
    if config_module.read_env_key() and not force:
        state.output.note("Already signed in. Pass --force to rotate the key.")
        return
    if state.no_input or not sys.stdin.isatty():
        state.output.fail("needs_browser", "login needs an interactive terminal and a browser.")
        raise typer.Exit(2)

    label = f"hai CLI ({socket.gethostname()})"
    try:
        with state.output.status("Waiting for browser sign-in..."):
            key = auth.login_and_mint(
                config_module.portal_base(),
                label,
                lambda url: state.output.note(f"Opening your browser. If it doesn't open, visit:\n  {url}"),
            )
    except (RuntimeError, OSError) as err:
        state.output.fail("login_failed", str(err))
        raise typer.Exit(1) from err

    path = config_module.save_env_key(key)
    state.output.note(f"Signed in. Wrote {config_module.TOKEN_VAR} to [bold]{path}[/bold].")


@app.command()
def logout(ctx: typer.Context) -> None:
    """Remove the stored API key from the local .env."""
    path = config_module.clear_env_key()
    get_state(ctx).output.note(f"Removed {config_module.TOKEN_VAR} from {path}." if path else "No stored key found.")


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Show the resolved region, endpoint, and API key (masked)."""
    cfg = get_state(ctx).config
    data = {
        "region": cfg.region,
        "base_url": client_module.effective_base_url(cfg),
        "api_key": config_module.mask(cfg.token) if cfg.token else None,
        "key_source": config_module.key_source(),
    }
    get_state(ctx).output.render(
        data,
        kv_table(
            [
                ("Region", data["region"]),
                ("Endpoint", data["base_url"]),
                ("API key", data["api_key"]),
                ("Key source", data["key_source"]),
            ]
        ),
    )


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

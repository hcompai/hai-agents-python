"""Shared per-invocation state and the error-handling decorator for commands."""

from __future__ import annotations

import functools
import sys
import typing
from dataclasses import dataclass

import typer
from hai_agents import Client
from hai_agents.core.api_error import ApiError

from .client import build_client
from .config import Config
from .output import Output


@dataclass
class AppState:
    output: Output
    config: Config
    assume_yes: bool
    no_input: bool = False


def get_state(ctx: typer.Context) -> AppState:
    return typing.cast(AppState, ctx.obj)


def get_client(ctx: typer.Context) -> Client:
    return build_client(get_state(ctx).config)


def confirm(ctx: typer.Context, prompt: str) -> None:
    """Abort unless confirmed. With --yes skip; without a TTY (or --no-input) fail rather than hang."""
    state = get_state(ctx)
    if state.assume_yes:
        return
    if state.no_input or not sys.stdin.isatty():
        state.output.fail("needs_confirmation", f"{prompt} Refusing to prompt without a TTY; pass --yes.")
        raise typer.Exit(2)
    if not typer.confirm(prompt):
        state.output.note("Aborted.")
        raise typer.Exit(1)


def safe(func: typing.Callable) -> typing.Callable:
    """Map SDK errors to a clean message (structured in json mode) and a non-zero exit code."""

    @functools.wraps(func)
    def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        ctx = kwargs.get("ctx") or (args[0] if args else None)
        output = get_state(ctx).output
        try:
            return func(*args, **kwargs)
        except ApiError as err:
            output.fail("api_error", str(err.body), status=err.status_code)
            raise typer.Exit(1) from err
        except TimeoutError as err:
            output.fail("timeout", str(err))
            raise typer.Exit(1) from err
        except ValueError as err:
            output.fail("invalid_input", str(err))
            raise typer.Exit(1) from err

    return wrapper

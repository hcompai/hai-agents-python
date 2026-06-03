"""Shared per-invocation state and the error-handling decorator for commands."""

from __future__ import annotations

import functools
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


def get_state(ctx: typer.Context) -> AppState:
    return typing.cast(AppState, ctx.obj)


def get_client(ctx: typer.Context) -> Client:
    return build_client(get_state(ctx).config)


def confirm(ctx: typer.Context, prompt: str) -> None:
    """Abort unless confirmed; with --yes (or no TTY + --yes) skip the prompt."""
    state = get_state(ctx)
    if state.assume_yes:
        return
    if not typer.confirm(prompt):
        state.output.note("Aborted.")
        raise typer.Exit(1)


def safe(func: typing.Callable) -> typing.Callable:
    """Map SDK errors to a clean message on stderr and a non-zero exit code."""

    @functools.wraps(func)
    def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        ctx = kwargs.get("ctx") or (args[0] if args else None)
        try:
            return func(*args, **kwargs)
        except ApiError as err:
            get_state(ctx).output.error(f"{err.status_code or 'request failed'}: {err.body}")
            raise typer.Exit(1) from err
        except (ValueError, TimeoutError) as err:
            get_state(ctx).output.error(str(err))
            raise typer.Exit(1) from err

    return wrapper

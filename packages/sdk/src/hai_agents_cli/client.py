"""Build a configured SDK client from resolved CLI config."""

from __future__ import annotations

import typer
from hai_agents import Client, HaiAgentsEnvironment

from .config import Config

_REGIONS = {"eu": HaiAgentsEnvironment.EU, "us": HaiAgentsEnvironment.US}


def build_client(cfg: Config) -> Client:
    if not cfg.token:
        raise typer.BadParameter("No API key. Set HAI_API_KEY, pass --token, or run 'hai configure' / 'hai login'.")
    if cfg.base_url:
        return Client(token=cfg.token, base_url=cfg.base_url)
    environment = _REGIONS.get(cfg.region)
    if environment is None:
        raise typer.BadParameter(f"Unknown region '{cfg.region}' (expected 'eu' or 'us').")
    return Client(token=cfg.token, environment=environment)

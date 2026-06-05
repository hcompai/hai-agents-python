"""Client construction shared by the CLI and MCP server."""

from __future__ import annotations

import os
from collections.abc import Callable

from hai_agents import AsyncClient, Client

API_KEY_ENV_VARS = ("HAI_API_KEY", "H_API_KEY")
BASE_URL_ENV_VARS = ("HAI_API_BASE_URL", "HAI_BASE_URL", "H_API_BASE_URL")


def resolve_api_key(explicit_api_key: str | None = None) -> str:
    """Return the configured API key or raise a clear error.

    Args:
        explicit_api_key: Optional key supplied by the caller.

    Returns:
        API key string.

    Raises:
        RuntimeError: If no API key is available.
    """
    key = explicit_api_key or _first_env(API_KEY_ENV_VARS)
    if not key:
        env_names = " or ".join(API_KEY_ENV_VARS)
        raise RuntimeError(f"No API key found. Set {env_names}, or pass --api-key.")
    return key


def resolve_base_url(explicit_base_url: str | None = None) -> str | None:
    """Return a base URL override when configured.

    Args:
        explicit_base_url: Optional base URL supplied by the caller.

    Returns:
        Base URL string, or None to let the SDK choose its default environment.
    """
    return explicit_base_url or _first_env(BASE_URL_ENV_VARS)


def make_client(api_key: str | None = None, base_url: str | None = None) -> Client:
    """Build a synchronous SDK client.

    Args:
        api_key: Optional API key override.
        base_url: Optional Agent Platform base URL override.

    Returns:
        Configured SDK client.
    """
    kwargs = _client_kwargs(api_key, base_url)
    return Client(**kwargs)


def make_async_client(api_key: str | None = None, base_url: str | None = None) -> AsyncClient:
    """Build an asynchronous SDK client.

    Args:
        api_key: Optional API key override.
        base_url: Optional Agent Platform base URL override.

    Returns:
        Configured async SDK client.
    """
    kwargs = _client_kwargs(api_key, base_url)
    return AsyncClient(**kwargs)


def _client_kwargs(api_key: str | None, base_url: str | None) -> dict[str, str]:
    kwargs = {"api_key": resolve_api_key(api_key)}
    resolved_base_url = resolve_base_url(base_url)
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    return kwargs


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None

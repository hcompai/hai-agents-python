"""Client construction for the MCP server."""

from __future__ import annotations

import os
from collections.abc import Callable
from urllib.parse import urljoin

from hai_agents import AsyncClient

ApiKey = str | Callable[[], str]

API_KEY_ENV_VARS = ("HAI_API_KEY", "H_API_KEY")
BASE_URL_ENV_VARS = ("HAI_API_BASE_URL", "HAI_BASE_URL", "H_API_BASE_URL")


def resolve_api_key(explicit_api_key: ApiKey | None = None) -> ApiKey:
    """Return the configured API key or raise a clear error.

    Args:
        explicit_api_key: Optional key supplied by the caller.

    Returns:
        API key string or token callback.

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


def make_async_client(api_key: ApiKey | None = None, base_url: str | None = None) -> AsyncClient:
    """Build an asynchronous SDK client.

    Args:
        api_key: Optional API key override.
        base_url: Optional Agent Platform base URL override.

    Returns:
        Configured async SDK client.
    """
    kwargs: dict[str, ApiKey | str] = {"api_key": resolve_api_key(api_key)}
    resolved_base_url = resolve_base_url(base_url)
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    return AsyncClient(**kwargs)


def absolute_share_url(client: AsyncClient, share_path: str) -> str:
    """Return a clickable share URL from the SDK share path.

    Args:
        client: Configured SDK client.
        share_path: Path returned by `share_session`.

    Returns:
        Absolute share URL.
    """
    if share_path.startswith(("http://", "https://")):
        return share_path
    return urljoin(client._client_wrapper.get_base_url().rstrip("/") + "/", share_path.lstrip("/"))


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None

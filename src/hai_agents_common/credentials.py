"""Resolve, construct, and persist Agent API credentials for the CLI and MCP server."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin

from dotenv import dotenv_values, set_key, unset_key

from hai_agents import AsyncClient, Client

ApiKey = str | Callable[[], str]

API_KEY_VAR = "HAI_API_KEY"
API_KEY_ENV_VARS = (API_KEY_VAR, "H_API_KEY")
BASE_URL_ENV_VARS = ("HAI_API_BASE_URL", "HAI_BASE_URL", "H_API_BASE_URL")

PORTAL_BASE = "https://portal.production.hcompany.ai"

LOCAL_ENV_PATH = Path(".env")
GLOBAL_ENV_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "hai" / ".env"


def portal_base() -> str:
    """Portal origin used by `hai login`."""
    return os.environ.get("HAI_PORTAL_URL") or PORTAL_BASE


def current_api_key(explicit: ApiKey | None = None) -> ApiKey | None:
    """Resolved API key, or None if none is configured."""
    return explicit or _lookup(API_KEY_ENV_VARS)


def resolve_api_key(explicit: ApiKey | None = None) -> ApiKey:
    """Resolved API key, or raise with guidance if none is configured."""
    key = current_api_key(explicit)
    if not key:
        env_names = " or ".join(API_KEY_ENV_VARS)
        raise RuntimeError(f"No API key found. Run `hai login`, set {env_names}, or pass --api-key.")
    return key


def resolve_base_url(explicit: str | None = None) -> str | None:
    """Resolved base URL override, or None to use the SDK default."""
    return explicit or _lookup(BASE_URL_ENV_VARS)


def make_client(api_key: ApiKey | None = None, base_url: str | None = None) -> Client:
    """Build a synchronous SDK client from resolved credentials."""
    return Client(**_client_kwargs(api_key, base_url))


def make_async_client(api_key: ApiKey | None = None, base_url: str | None = None) -> AsyncClient:
    """Build an asynchronous SDK client from resolved credentials."""
    return AsyncClient(**_client_kwargs(api_key, base_url))


def absolute_share_url(client: Client | AsyncClient, share_path: str) -> str:
    """Turn the SDK share path into a clickable absolute URL."""
    if share_path.startswith(("http://", "https://")):
        return share_path
    base = client._client_wrapper.get_base_url().rstrip("/") + "/"
    return urljoin(base, share_path.lstrip("/"))


def save_api_key(key: str) -> Path:
    """Persist the API key to the global `.env` (chmod 600) and the process env."""
    GLOBAL_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not GLOBAL_ENV_PATH.exists():
        GLOBAL_ENV_PATH.write_text("", encoding="utf-8")
    with contextlib.suppress(OSError):
        GLOBAL_ENV_PATH.chmod(0o600)
    set_key(str(GLOBAL_ENV_PATH), API_KEY_VAR, key)
    os.environ[API_KEY_VAR] = key
    return GLOBAL_ENV_PATH


def clear_api_key() -> Path | None:
    """Remove the API key from the global `.env` and the process env. Idempotent."""
    os.environ.pop(API_KEY_VAR, None)
    if not GLOBAL_ENV_PATH.exists():
        return None
    with contextlib.suppress(KeyError):
        unset_key(str(GLOBAL_ENV_PATH), API_KEY_VAR)
    return GLOBAL_ENV_PATH


def api_key_source() -> str | None:
    """Where the resolved API key comes from, for `hai whoami`."""
    for name in API_KEY_ENV_VARS:
        if os.environ.get(name):
            return "environment"
    for path in _env_paths():
        if path.exists() and any(dotenv_values(path).get(name) for name in API_KEY_ENV_VARS):
            return str(path)
    return None


def _client_kwargs(api_key: ApiKey | None, base_url: str | None) -> dict[str, ApiKey | str]:
    kwargs: dict[str, ApiKey | str] = {"api_key": resolve_api_key(api_key)}
    resolved_base_url = resolve_base_url(base_url)
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    return kwargs


def _env_paths() -> tuple[Path, ...]:
    # CWD `.env` overrides the global config `.env`.
    return (LOCAL_ENV_PATH, GLOBAL_ENV_PATH)


def _lookup(names: tuple[str, ...]) -> str | None:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    for path in _env_paths():
        if not path.exists():
            continue
        values = dotenv_values(path)
        for name in names:
            if values.get(name):
                return values[name]
    return None

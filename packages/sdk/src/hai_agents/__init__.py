"""H Company Agent Platform — Python SDK.

This module is the hand-written entry point. The rest of the package
(``api/``, ``models/``, ``client.py``, etc.) is generated from
``openapi.json`` by ``openapi-python-client==0.28.3``.

Do NOT edit ``packages/sdk/src/hai_agents/__init__.py`` directly — it
is overwritten on every regen. Edit ``templates/__init__.py.static``
instead; the schema-sync workflow restores it after each regeneration.
"""

from __future__ import annotations

import ssl
from typing import Any

import httpx

from hai_agents.client import AuthenticatedClient as _AuthenticatedClient
from hai_agents.models.agent import Agent
from hai_agents.models.browser import Browser
from hai_agents.models.session import Session
from hai_agents.models.session_request import SessionRequest
from hai_agents.models.session_summary import SessionSummary
from hai_agents.models.skill import Skill
from hai_agents.polling import (
    SessionRunResult,
    async_run_session_until_done,
    async_wait_for_session,
    is_terminal_session_status,
    run_session_until_done,
    wait_for_session,
)

__all__ = [
    "Client",
    "AsyncClient",
    "Agent",
    "Browser",
    "Skill",
    "Session",
    "SessionRequest",
    "SessionSummary",
    "SessionRunResult",
    "async_run_session_until_done",
    "async_wait_for_session",
    "is_terminal_session_status",
    "run_session_until_done",
    "wait_for_session",
]


class Client(_AuthenticatedClient):
    """Sync Agent Platform SDK client.

    Args:
        api_key: Portal-H API key (``hk-*`` format). Sent as
            ``Authorization: Bearer <api_key>`` on every request.
        base_url: AgP base URL. Defaults to production.
        cookies: Cookies sent with every request.
        headers: Additional headers sent with every request.
        timeout: Maximum request duration. ``httpx.TimeoutException`` is raised
            if exceeded.
        verify_ssl: Whether to verify TLS certificates.
        follow_redirects: Whether to follow redirects.
        httpx_args: Extra keyword arguments forwarded to ``httpx.Client`` and
            ``httpx.AsyncClient``.
        raise_on_unexpected_status: Raise ``UnexpectedStatus`` instead of
            returning ``None`` for undocumented API statuses.

    Example:
        >>> from hai_agents import Client
        >>> client = Client(api_key="hk-...", base_url="https://agp.eu.hcompany.ai")
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://agp.eu.hcompany.ai",
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        verify_ssl: str | bool | ssl.SSLContext = True,
        follow_redirects: bool = False,
        httpx_args: dict[str, Any] | None = None,
        raise_on_unexpected_status: bool = True,
    ) -> None:
        super().__init__(
            base_url=base_url,
            token=api_key,
            cookies=cookies or {},
            headers=headers or {},
            timeout=timeout,
            verify_ssl=verify_ssl,
            follow_redirects=follow_redirects,
            httpx_args=httpx_args or {},
            raise_on_unexpected_status=raise_on_unexpected_status,
        )


class AsyncClient(Client):
    """Async Agent Platform SDK client.

    Same constructor as ``Client``. Use with ``asyncio``-flavoured endpoint
    functions (``asyncio()`` / ``asyncio_detailed()`` in each ``hai_agents.api.*`` module).

    Note: openapi-python-client 0.28.x does not generate separate sync/async
    *client* classes — it generates per-endpoint sync and async *functions* that
    both accept an ``AuthenticatedClient`` instance. ``Client`` and ``AsyncClient``
    here are the same underlying class, exposed under two names for ergonomic
    discoverability (so users can write `from hai_agents import AsyncClient`).

    Example:
        >>> from hai_agents import AsyncClient
        >>> from hai_agents.api.sessions import list_session_events
        >>> client = AsyncClient(api_key="hk-...")
        >>> events = await list_session_events.asyncio(client=client, id="…")
    """

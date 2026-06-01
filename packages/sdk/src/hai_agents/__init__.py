"""H Company Agent Platform — Python SDK.

This module is the hand-written entry point. The rest of the package
(``api/``, ``models/``, ``client.py``, etc.) is generated from
``openapi.json`` by ``openapi-python-client==0.28.3``.

Do NOT edit ``packages/sdk/src/hai_agents/__init__.py`` directly — it
is overwritten on every regen. Edit ``templates/__init__.py.static``
instead; the schema-sync workflow restores it after each regeneration.
"""

from __future__ import annotations

from hai_agents.client import AuthenticatedClient as _AuthenticatedClient
from hai_agents.models.agent import Agent
from hai_agents.models.browser import Browser
from hai_agents.models.create_environment import CreateEnvironment
from hai_agents.models.create_skill import CreateSkill
from hai_agents.models.environment_record import EnvironmentRecord
from hai_agents.models.session import Session
from hai_agents.models.session_request import SessionRequest
from hai_agents.models.session_summary import SessionSummary
from hai_agents.models.skill import Skill
from hai_agents.models.skill_record import SkillRecord
from hai_agents.models.update_environment import UpdateEnvironment
from hai_agents.models.update_skill import UpdateSkill

__all__ = [
    "Client",
    "AsyncClient",
    # Agent
    "Agent",
    # Environment specs (discriminated union members)
    "Browser",
    # Environment catalog
    "EnvironmentRecord",
    "CreateEnvironment",
    "UpdateEnvironment",
    # Skill
    "Skill",
    "SkillRecord",
    "CreateSkill",
    "UpdateSkill",
    # Session
    "Session",
    "SessionRequest",
    "SessionSummary",
]


class Client(_AuthenticatedClient):
    """Sync Agent Platform SDK client.

    Args:
        api_key: Portal-H API key (``hk-*`` format). Sent as
            ``Authorization: Bearer <api_key>`` on every request.
        base_url: AgP base URL. Defaults to production.

    Example:
        >>> from hai_agents import Client
        >>> client = Client(api_key="hk-...", base_url="https://agp.eu.hcompany.ai")
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://agp.eu.hcompany.ai",
    ) -> None:
        super().__init__(base_url=base_url, token=api_key)


class AsyncClient(_AuthenticatedClient):
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

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://agp.eu.hcompany.ai",
    ) -> None:
        super().__init__(base_url=base_url, token=api_key)

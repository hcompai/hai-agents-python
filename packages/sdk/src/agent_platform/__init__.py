"""H Company Agent Platform — Python SDK.

This module is the hand-written entry point. The rest of the package
(``api/``, ``models/``, ``client.py``, etc.) is generated from
``openapi.json`` by ``openapi-python-client==0.28.3``.

Do NOT edit ``packages/sdk/src/agent_platform/__init__.py`` directly — it
is overwritten on every regen. Edit ``templates/__init__.py.static``
instead; the schema-sync workflow restores it after each regeneration.
"""

from __future__ import annotations

from agent_platform.client import AuthenticatedClient as _AuthenticatedClient
from agent_platform.models.agent import Agent
from agent_platform.models.agent_record import AgentRecord
from agent_platform.models.browser import Browser
from agent_platform.models.code_sandbox import CodeSandbox
from agent_platform.models.create_agent import CreateAgent
from agent_platform.models.create_environment import CreateEnvironment
from agent_platform.models.create_memory import CreateMemory
from agent_platform.models.create_skill import CreateSkill
from agent_platform.models.environment_record import EnvironmentRecord
from agent_platform.models.mcp import MCP
from agent_platform.models.memory import Memory
from agent_platform.models.memory_record import MemoryRecord
from agent_platform.models.session import Session
from agent_platform.models.session_request import SessionRequest
from agent_platform.models.session_summary import SessionSummary
from agent_platform.models.skill import Skill
from agent_platform.models.skill_record import SkillRecord
from agent_platform.models.update_environment import UpdateEnvironment
from agent_platform.models.update_memory import UpdateMemory
from agent_platform.models.update_skill import UpdateSkill

__all__ = [
    "Client",
    "AsyncClient",
    # Agent
    "Agent",
    "AgentRecord",
    "CreateAgent",
    # Environment specs (discriminated union members)
    "Browser",
    "CodeSandbox",
    "MCP",
    "Memory",
    # Environment catalog
    "EnvironmentRecord",
    "CreateEnvironment",
    "UpdateEnvironment",
    # Skill
    "Skill",
    "SkillRecord",
    "CreateSkill",
    "UpdateSkill",
    # Memory catalog
    "MemoryRecord",
    "CreateMemory",
    "UpdateMemory",
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
        >>> from agent_platform import Client
        >>> client = Client(api_key="hk-...", base_url="https://agp.hcompany.ai")
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://agp.hcompany.ai",
    ) -> None:
        super().__init__(base_url=base_url, token=api_key)


class AsyncClient(_AuthenticatedClient):
    """Async Agent Platform SDK client.

    Same constructor as ``Client``. Use with ``asyncio``-flavoured endpoint
    functions (``asyncio()`` / ``asyncio_detailed()`` in each ``agent_platform.api.*`` module).

    Note: openapi-python-client 0.28.x does not generate separate sync/async
    *client* classes — it generates per-endpoint sync and async *functions* that
    both accept an ``AuthenticatedClient`` instance. ``Client`` and ``AsyncClient``
    here are the same underlying class, exposed under two names for ergonomic
    discoverability (so users can write `from agent_platform import AsyncClient`).

    Example:
        >>> from agent_platform import AsyncClient
        >>> from agent_platform.api.sessions import list_session_events
        >>> client = AsyncClient(api_key="hk-...")
        >>> events = await list_session_events.asyncio(client=client, id="…")
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://agp.hcompany.ai",
    ) -> None:
        super().__init__(base_url=base_url, token=api_key)

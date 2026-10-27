"""`holo mcp`: `holo run` as MCP tools that coding agents call over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import AsyncIterator
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP

from hai_agents import AsyncClient
from hai_agents_common import credentials
from hai_agents_local.killswitch import KILL_SWITCH_UNAVAILABLE_HINT, arm_esc_listener
from hai_agents_local.routing import split_revision
from hai_agents_local.sessions import local_environment_kinds_async

from . import holo_dir, tools, ui

INSTRUCTIONS = (
    "`run_agent` hands a task to an H agent and returns its answer. Cloud agents browse the web; "
    "`h/holo-desktop` drives this machine with the real cursor and keyboard. "
    "The agent sees none of this conversation: write a self-contained task that keeps the user's own words. "
    "Confirm with the user before an agent sends, deletes, pays or changes settings."
)
# Bridges in one process share this machine's mouse and keyboard.
_this_machine = asyncio.Lock()


@contextlib.asynccontextmanager
async def _kill_switch(ctx: Context, kinds: list[str]) -> AsyncIterator[None]:
    """Double-Esc stops a run that drives the desktop, which steals focus from the host."""
    if not {"desktop", "workstation"} & set(kinds):
        yield
        return
    if (listener := arm_esc_listener()) is None:
        await ctx.info(KILL_SWITCH_UNAVAILABLE_HINT)
    try:
        yield
    finally:
        if listener is not None:
            listener.stop()


@contextlib.asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncIterator[dict[bool, AsyncClient]]:
    clients: dict[bool, AsyncClient] = {}
    try:
        yield clients
    finally:
        for client in clients.values():
            await client.aclose()


server = FastMCP("holo", instructions=INSTRUCTIONS, lifespan=_lifespan, log_level="WARNING")


async def _client(ctx: Context, local: bool = False) -> AsyncClient:
    """The local runtime runs sessions only; agents and their specs come from the cloud client."""
    clients = ctx.request_context.lifespan_context
    if local not in clients:
        if local and (base_url := credentials.resolve_base_url()):
            # The spawned runtime reads its endpoint from the environment.
            os.environ[credentials.BASE_URL_VAR] = base_url
        clients[local] = await AsyncClient.local() if local else credentials.make_async_client()
    return clients[local]


@server.tool()
async def run_agent(task: str, ctx: Context, agent: str | None = None, local: bool = False) -> str:
    """Run `task` and return the answer; blocks until the agent finishes.

    `agent` is a name from list_agents, by default the user's default agent. `local` runs the agent loop on
    this machine rather than in the cloud.
    """
    cloud, agent = await _client(ctx), agent or credentials.default_agent()
    params: dict[str, Any] = {"agent": agent, "messages": task}
    if local or holo_dir.customized():
        name, revision = split_revision(agent)
        spec = (await cloud.agents.get_agent(name, revision=revision, resolve=local)).model_dump(
            mode="json", exclude_none=True
        )
        if local:
            params["agent"] = spec
        if holo_dir.customized():
            params["overrides"] = holo_dir.overrides(spec)
    kinds = await local_environment_kinds_async(cloud, agent)
    client = await _client(ctx, local)
    async with _this_machine if kinds else contextlib.nullcontext(), _kill_switch(ctx, kinds):
        handle = await client.start_session(**params)
        try:
            async for event in handle.stream():
                await _report(ctx, event)
            result = await handle.wait_for_completion()
        finally:
            # A settled session keeps its machine claimed; only a shield lets the cancel outlive the call's own.
            with anyio.CancelScope(shield=True), contextlib.suppress(Exception):
                await handle.cancel()
    if result.status not in ("completed", "idle"):
        raise RuntimeError(f"agent {result.status}: {result.error or 'no answer'}")
    return str(result.answer or "")


async def _report(ctx: Context, event: Any) -> None:
    kind, data, _ = ui.unwrap(event)
    if kind != "policy_event":
        return
    for req in data.get("tool_reqs") or []:
        if isinstance(req, dict) and req.get("tool_name") != "answer":
            verb, target = tools.label(req)
            await ctx.info(f"{verb.capitalize()} {target}".strip())


@server.tool()
async def list_agents(ctx: Context, search: str | None = None) -> str:
    """Agents `run_agent` can use, one `name: description` per line."""
    page = await (await _client(ctx)).agents.list_agents(search=search, size=100)
    return "\n".join(f"{item.name}: {item.description or ''}".strip() for item in page.items)


def serve() -> None:
    # A host stops its server with SIGTERM; as KeyboardInterrupt it still cancels running sessions.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    server.run()

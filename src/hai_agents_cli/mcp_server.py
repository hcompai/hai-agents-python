"""`holo mcp`: `holo run` as MCP tools that coding agents call over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator

import anyio
from mcp.server.fastmcp import Context, FastMCP

from hai_agents import AsyncClient
from hai_agents_common import credentials

from . import desktop_agent, tools, ui

INSTRUCTIONS = (
    "`run_agent` hands a task to an H agent and returns its answer: a cloud agent that browses the web, "
    "or with `local` the agent that drives this desktop with the real cursor and keyboard. "
    "The agent sees none of this conversation: write a self-contained task that keeps the user's own words. "
    "Confirm with the user before an agent sends, deletes, pays or changes settings."
)
# The local runtime hands this desktop to the newest session, which would cut off a running one.
_one_desktop_task = asyncio.Lock()


@contextlib.asynccontextmanager
async def _clients(_: FastMCP) -> AsyncIterator[dict[bool, AsyncClient]]:
    clients: dict[bool, AsyncClient] = {}
    try:
        yield clients
    finally:
        for client in clients.values():
            await client.aclose()


server = FastMCP("holo", instructions=INSTRUCTIONS, lifespan=_clients, log_level="WARNING")


async def _client(ctx: Context, local: bool) -> AsyncClient:
    clients = ctx.request_context.lifespan_context
    if local not in clients:
        clients[local] = await AsyncClient.local() if local else credentials.make_async_client()
    return clients[local]


@server.tool()
async def run_agent(task: str, ctx: Context, agent: str | None = None, local: bool = False) -> str:
    """Run `task` and return the answer; blocks until the agent finishes.

    `agent` is a name from list_agents, by default the user's default agent. `local` runs the agent that
    drives this desktop instead.
    """
    if local and agent:
        raise ValueError("local runs this desktop's own agent; drop agent")
    async with _one_desktop_task if local else contextlib.nullcontext():
        client = await _client(ctx, local)
        handle = await client.start_session(
            agent=desktop_agent.agent() if local else agent or credentials.default_agent(), messages=task
        )
        try:
            async for event in handle.stream():
                kind, data, _ = ui.unwrap(event)
                if kind != "policy_event":
                    continue
                for req in data.get("tool_reqs") or []:
                    if isinstance(req, dict) and req.get("tool_name") != "answer":
                        verb, target = tools.label(req)
                        await ctx.info(f"{verb.capitalize()} {target}".strip())
            result = await handle.wait_for_completion()
        finally:
            # A settled session keeps its machine claimed; only a shield lets the cancel outlive the call's own.
            with anyio.CancelScope(shield=True), contextlib.suppress(Exception):
                await handle.cancel()
    if result.status not in ("completed", "idle"):
        raise RuntimeError(f"agent {result.status}: {result.error or 'no answer'}")
    return str(result.answer or "")


@server.tool()
async def list_agents(ctx: Context, search: str | None = None) -> str:
    """Agents `run_agent` can use, one `name: description` per line."""
    page = await (await _client(ctx, False)).agents.list_agents(search=search, size=100)
    return "\n".join(f"{item.name}: {item.description or ''}".strip() for item in page.items)


def serve() -> None:
    # A host stops its server with SIGTERM; as KeyboardInterrupt it still cancels running sessions.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    server.run()

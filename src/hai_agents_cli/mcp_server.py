"""`holo mcp serve`: this desktop's agent as one MCP tool that coding agents call over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator

import anyio
from mcp.server.fastmcp import Context, FastMCP

from hai_agents import AsyncClient

from . import desktop_agent, tools, ui

INSTRUCTIONS = (
    "`holo_desktop` drives the user's own desktop with the real cursor and keyboard. Use it for native apps, "
    "system settings and the user's logged-in browser, not for work files, a shell or the web can do. "
    "It sees none of this conversation: write a self-contained task that keeps the user's own words. "
    "Confirm with the user before it sends, deletes, pays or changes settings. One task runs at a time."
)
# The local runtime hands this desktop to the newest session, which would cut off a running one.
_one_task_at_a_time = asyncio.Lock()


@contextlib.asynccontextmanager
async def _local_client(_: FastMCP) -> AsyncIterator[AsyncClient]:
    client = await AsyncClient.local()
    try:
        yield client
    finally:
        await client.aclose()


server = FastMCP("holo", instructions=INSTRUCTIONS, lifespan=_local_client, log_level="WARNING")


@server.tool()
async def holo_desktop(task: str, ctx: Context) -> str:
    """Do a task on the user's desktop and return the agent's answer; blocks until it finishes."""
    client: AsyncClient = ctx.request_context.lifespan_context
    async with _one_task_at_a_time:
        handle = await client.start_session(agent=desktop_agent.agent(), messages=task)
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
            # A settled session keeps the desktop claimed; only a shield lets the cancel outlive the call's own.
            with anyio.CancelScope(shield=True), contextlib.suppress(Exception):
                await handle.cancel()
    if result.status not in ("completed", "idle"):
        raise RuntimeError(f"holo {result.status}: {result.error or 'no answer'}")
    return str(result.answer or "")


def serve() -> None:
    # A host stops its server with SIGTERM; as KeyboardInterrupt it still cancels the running session.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    server.run()

"""FastMCP server exposing the H Agent API SDK."""

from __future__ import annotations

import inspect
import os
from typing import Optional

import typer
from fastmcp import Context, FastMCP

from hai_agents_extras import runners
from hai_agents_extras._client import make_async_client
from hai_agents_extras._json import to_jsonable

mcp = FastMCP(
    name="hai-agents",
    instructions="Run and steer H Company Agent API sessions.",
)


@mcp.tool
async def run_agent(
    task: str,
    ctx: Context,
    agent: str = runners.DEFAULT_AGENT,
    max_steps: int = 20,
    max_time_s: float = 180.0,
    include_events: bool = False,
) -> dict:
    """Run an H agent task."""
    params = runners.RunAgentParams(task=task, agent=agent, max_steps=max_steps, max_time_s=max_time_s)
    event_count = 0

    async def on_event(event) -> None:
        nonlocal event_count
        event_count += 1
        await _report_progress(ctx, event_count, event.type)

    result = await runners.async_run_agent(_async_client(), params, on_event=on_event)
    payload = {
        "session_id": result.id,
        "status": str(getattr(result.status, "value", result.status)),
        "answer": result.answer,
    }
    if include_events:
        payload["events"] = result.events
    return to_jsonable(payload)


@mcp.tool
async def get_session(session_id: str) -> dict:
    """Fetch a full session envelope."""
    return to_jsonable(await runners.async_get_session(_async_client(), session_id))


@mcp.tool
async def cancel_session(session_id: str) -> dict:
    """Cancel a session."""
    await runners.async_cancel_session(_async_client(), session_id)
    return {"ack": True}


@mcp.tool
async def send_message(session_id: str, message: str) -> dict:
    """Send a user message to a live session."""
    await runners.async_send_message(_async_client(), session_id, message)
    return {"ack": True}


@mcp.tool
async def share_session(session_id: str) -> dict:
    """Share a session and return its URL/path."""
    share_url = await runners.async_share_session(_async_client(), session_id)
    return {"share_url": share_url}


def serve(
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key. Defaults to HAI_API_KEY or H_API_KEY."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Override the Agent Platform base URL."),
) -> None:
    """Start the stdio MCP server."""
    if api_key is not None:
        os.environ["HAI_API_KEY"] = api_key
    if base_url is not None:
        os.environ["HAI_API_BASE_URL"] = base_url
    run_server()


def run_server() -> None:
    mcp.run(transport="stdio")


def main() -> None:
    typer.run(serve)


def _async_client():
    return make_async_client()


async def _report_progress(ctx: Context, progress: int, message: str) -> None:
    report = getattr(ctx, "report_progress", None)
    if report is None:
        return
    result = report(progress=float(progress), message=message)
    if inspect.isawaitable(result):
        await result

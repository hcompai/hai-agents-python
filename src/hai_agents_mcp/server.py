"""MCP server exposing the H Agent API SDK."""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Sequence

from mcp.server.fastmcp import FastMCP

from hai_agents import async_run_session
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage

from ._client import absolute_share_url, make_async_client
from ._json import to_jsonable

DEFAULT_AGENT = "h/web-surfer-holo3-1-35b"

mcp = FastMCP(
    name="hai-agents",
    instructions=(
        "Run and steer H Company Agent API sessions. Use run_agent for a complete one-shot task, "
        "send_message to continue an existing session, and list_agents to inspect available agents."
    ),
)


@dataclass(frozen=True)
class ServerConfig:
    api_key: str | None = None
    base_url: str | None = None


_config = ServerConfig()


@mcp.tool()
async def run_agent(
    task: str,
    agent: str = DEFAULT_AGENT,
    max_steps: int = 20,
    max_time_s: float = 180.0,
) -> dict:
    """Run a self-contained task and return the final Agent API session result.

    Args:
        task: Plain-language task to send as the first user message.
        agent: Registered H agent name.
        max_steps: Maximum reasoning steps.
        max_time_s: Maximum backend wall-clock seconds.

    Returns:
        Session id, terminal status, and final answer when available.
    """
    client = _async_client()
    result = await async_run_session(
        client,
        agent=agent,
        messages=task,
        max_steps=max_steps,
        max_time_s=max_time_s,
        timeout_seconds=max_time_s + 30.0,
    )
    return to_jsonable(
        {
            "session_id": result.id,
            "status": str(result.status),
            "answer": result.answer,
        }
    )


@mcp.tool()
async def list_agents(search: str | None = None, page: int = 1, size: int = 20) -> dict:
    """List agents visible to the caller.

    Args:
        search: Optional case-insensitive match over agent name or description.
        page: Page number, one-based.
        size: Number of agents to return.

    Returns:
        Page of agent definitions.
    """
    return to_jsonable(await _async_client().agents.list_agents(search=search, page=page, size=size))


@mcp.tool()
async def get_session(session_id: str) -> dict:
    """Fetch a full session envelope.

    Args:
        session_id: Session identifier.

    Returns:
        Session envelope.
    """
    return to_jsonable(await _async_client().sessions.get_session(session_id))


@mcp.tool()
async def cancel_session(session_id: str) -> dict:
    """Cancel a session.

    Args:
        session_id: Session identifier.

    Returns:
        Acknowledgement.
    """
    await _async_client().sessions.cancel_session(session_id)
    return {"ack": True}


@mcp.tool()
async def send_message(session_id: str, message: str) -> dict:
    """Send a user message to a live session.

    Args:
        session_id: Session identifier.
        message: Message text.

    Returns:
        Acknowledgement.
    """
    request = SendSessionMessagesRequestBody_UserMessage(message=message)
    await _async_client().sessions.send_session_messages(session_id, request=request)
    return {"ack": True}


@mcp.tool()
async def share_session(session_id: str) -> dict:
    """Share a session and return a clickable URL.

    Args:
        session_id: Session identifier.

    Returns:
        Share URL.
    """
    client = _async_client()
    link = await client.sessions.share_session(session_id)
    return {"share_url": absolute_share_url(client, link.share_url)}


def serve(api_key: str | None = None, base_url: str | None = None) -> None:
    """Start the stdio MCP server.

    Args:
        api_key: Optional API key override.
        base_url: Optional Agent Platform base URL override.
    """
    global _config
    _config = ServerConfig(api_key=api_key, base_url=base_url)
    mcp.run(transport="stdio")


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    serve(api_key=args.api_key, base_url=args.base_url)


def _async_client():
    return make_async_client(api_key=_config.api_key, base_url=_config.base_url)


def _parser() -> ArgumentParser:
    parser = ArgumentParser(description="Start the H Agent API MCP stdio server.")
    parser.add_argument("--api-key", help="API key. Defaults to HAI_API_KEY or H_API_KEY.")
    parser.add_argument("--base-url", help="Override the Agent Platform base URL.")
    return parser

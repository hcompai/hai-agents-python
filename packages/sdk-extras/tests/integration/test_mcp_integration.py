from __future__ import annotations

import json

import pytest
from fastmcp import Client
from hai_agents_extras.mcp import server


@pytest.mark.integration
async def test_mcp_lists_tools() -> None:
    async with Client(server.mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert "run_agent" in names


@pytest.mark.integration
async def test_mcp_run_agent_live(api_key: str, base_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAI_API_KEY", api_key)
    monkeypatch.setenv("HAI_API_BASE_URL", base_url)

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "run_agent",
            {"task": "Reply with exactly: hello", "max_steps": 3, "max_time_s": 60.0},
        )

    payload = _tool_payload(result)
    assert payload["session_id"]
    assert payload["status"] in {"completed", "idle"}
    assert payload["answer"] is not None


def _tool_payload(result) -> dict:
    data = getattr(result, "data", None)
    if data is not None:
        return data
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"Cannot extract tool payload from {result!r}")

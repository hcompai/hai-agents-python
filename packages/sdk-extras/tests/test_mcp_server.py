from __future__ import annotations

import json

import pytest
from fastmcp import Client
from hai_agents_extras.mcp import server

from hai_agents.polling import SessionRunResult


async def test_mcp_lists_shape_a_tools() -> None:
    async with Client(server.mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert {"run_agent", "get_session", "cancel_session", "send_message", "share_session"} <= names


async def test_run_agent_tool_omits_events_by_default(monkeypatch) -> None:
    monkeypatch.setattr(server, "_async_client", lambda: object())
    monkeypatch.setattr(server.runners, "async_run_agent", _fake_async_run_agent)

    async with Client(server.mcp) as client:
        result = await client.call_tool("run_agent", {"task": "hello"})

    payload = _tool_payload(result)
    assert payload == {"answer": "done", "session_id": "sess_1", "status": "completed"}


async def test_run_agent_schema_does_not_advertise_answer_format() -> None:
    async with Client(server.mcp) as client:
        tools = await client.list_tools()

    run_tool = next(tool for tool in tools if tool.name == "run_agent")
    schema = getattr(run_tool, "inputSchema", None) or getattr(run_tool, "input_schema", {})
    assert "answer_format" not in json.dumps(schema)


async def _fake_async_run_agent(client, params, *, on_event):
    return SessionRunResult(id="sess_1", status="completed", events=[], next_from_index=0, final_changes=_Answer())


def _tool_payload(result):
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


class _Answer:
    answer = "done"

from __future__ import annotations

import json

from hai_agents.polling import SessionRunResult
from hai_agents_mcp import server


async def test_mcp_lists_agent_tools() -> None:
    tools = await server.mcp.list_tools()

    names = {tool.name for tool in tools}
    assert {"run_agent", "list_agents", "get_session", "cancel_session", "send_message", "share_session"} <= names


async def test_run_agent_tool_returns_session_payload(monkeypatch) -> None:
    monkeypatch.setattr(server, "_async_client", lambda: object())
    monkeypatch.setattr(server, "async_run_session", _fake_async_run_session)

    result = await server.mcp.call_tool("run_agent", {"task": "hello"})

    payload = _tool_payload(result)
    assert payload == {"answer": "done", "session_id": "sess_1", "status": "completed"}


async def test_run_agent_schema_does_not_advertise_answer_format() -> None:
    tools = await server.mcp.list_tools()

    run_tool = next(tool for tool in tools if tool.name == "run_agent")
    assert "answer_format" not in json.dumps(run_tool.inputSchema)


def test_mcp_entrypoint_parses_connection_options(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(server.mcp, "run", lambda transport: captured.update({"transport": transport}))

    server.main(["--api-key", "hk-test", "--base-url", "https://example.test"])

    assert server._config.api_key == "hk-test"
    assert server._config.base_url == "https://example.test"
    assert captured == {"transport": "stdio"}


async def _fake_async_run_session(client, **kwargs):
    assert kwargs["messages"] == "hello"
    return SessionRunResult(id="sess_1", status="completed", events=[], next_from_index=0, final_changes=_Answer())


def _tool_payload(result):
    if isinstance(result, dict):
        return result
    if result:
        text = getattr(result[0], "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"Cannot extract tool payload from {result!r}")


class _Answer:
    answer = "done"

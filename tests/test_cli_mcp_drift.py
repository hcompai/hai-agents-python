from __future__ import annotations

import inspect
from pathlib import Path

import tomllib

import hai_agents
from hai_agents import AsyncClient, Client
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage


def test_sdk_exposes_symbols_used_by_cli_and_mcp() -> None:
    for name in [
        "AsyncClient",
        "Client",
        "SessionRunResult",
        "async_run_session",
        "run_session",
    ]:
        assert hasattr(hai_agents, name), f"hai_agents.{name} disappeared"


def test_session_method_contracts_still_match() -> None:
    sync_sessions = Client(api_key="hk-test", base_url="https://example.test").sessions
    async_sessions = AsyncClient(api_key="hk-test", base_url="https://example.test").sessions

    assert {"agent", "messages", "max_steps", "max_time_s"} <= _params(sync_sessions.create_session)
    assert "request" in _params(sync_sessions.send_session_messages)

    for method_name in [
        "get_session",
        "cancel_session",
        "send_session_messages",
        "share_session",
    ]:
        assert hasattr(sync_sessions, method_name)
        assert hasattr(async_sessions, method_name)


def test_message_request_body_still_has_message_field() -> None:
    request = SendSessionMessagesRequestBody_UserMessage(message="hello")

    assert request.type == "user_message"
    assert request.message == "hello"


def test_project_exposes_cli_and_mcp_extras() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert set(pyproject["project"]["optional-dependencies"]) >= {"cli", "mcp", "all"}
    assert pyproject["project"]["scripts"]["hai"] == "hai_agents_cli.app:main"
    assert pyproject["project"]["scripts"]["hai-mcp"] == "hai_agents_mcp.server:main"


def _params(fn) -> set[str]:
    return set(inspect.signature(fn).parameters)

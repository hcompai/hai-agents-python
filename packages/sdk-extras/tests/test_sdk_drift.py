from __future__ import annotations

import inspect

from hai_agents_extras.runners import RunAgentParams

import hai_agents
from hai_agents import AsyncClient, Client
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage


def test_sdk_exposes_symbols_used_by_extras() -> None:
    for name in [
        "Agent",
        "AsyncClient",
        "Client",
        "Session",
        "SessionRunResult",
        "TrajectoryEvent",
        "run_session",
    ]:
        assert hasattr(hai_agents, name), f"hai_agents.{name} disappeared"


def test_session_method_contracts_still_match() -> None:
    sync_sessions = Client(api_key="hk-test", base_url="https://example.test").sessions
    async_sessions = AsyncClient(api_key="hk-test", base_url="https://example.test").sessions

    assert {"agent", "messages", "max_steps", "max_time_s"} <= _params(sync_sessions.create_session)
    assert {"from_index", "include_events", "wait_for_seconds"} <= _params(sync_sessions.get_session_changes)
    assert "request" in _params(sync_sessions.send_session_messages)

    for method_name in [
        "get_session",
        "get_session_status",
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


def test_run_params_are_shape_a_only() -> None:
    assert "answer_format" not in RunAgentParams.model_fields
    assert "environments" not in RunAgentParams.model_fields


def _params(fn) -> set[str]:
    return set(inspect.signature(fn).parameters)

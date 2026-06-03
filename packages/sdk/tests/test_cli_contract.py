"""Drift guards: the CLI wraps the generated SDK, so these assert the SDK still
exposes the surface the CLI relies on, and that every command wires up. No network.

When an SDK regeneration renames or drops something the CLI uses, one of these
fails on the auto-sync PR instead of in a user's terminal.
"""

from __future__ import annotations

import inspect
import json

import hai_agents
import pytest
from hai_agents import Client
from hai_agents_cli.app import app
from hai_agents_cli.output import Output, OutputMode
from typer.main import get_command
from typer.testing import CliRunner

runner = CliRunner()

_SDK_SYMBOLS = [
    "Client",
    "AsyncClient",
    "HaiAgentsEnvironment",
    "run_session_until_done",
    "is_terminal_session_status",
    "SendSessionMessagesRequestBody_UserMessage",
    "SendSessionMessagesRequestBody_Batch",
    "CreateEnvironmentRequest_Web",
    "UpdateEnvironmentRequestBody_Web",
]


def _params(fn) -> set[str]:
    return set(inspect.signature(fn).parameters)


def _client() -> Client:
    return Client(token="contract-test", base_url="http://localhost")


@pytest.mark.parametrize("name", _SDK_SYMBOLS)
def test_sdk_exposes_symbol(name: str) -> None:
    assert hasattr(hai_agents, name), f"hai_agents.{name} is gone; CLI imports would break."


def test_api_error_importable() -> None:
    from hai_agents.core.api_error import ApiError  # noqa: F401


def test_session_method_signatures() -> None:
    sessions = _client().sessions
    assert {
        "agent",
        "messages",
        "max_steps",
        "max_time_s",
        "idle_timeout_s",
        "group_id",
        "parent_session_id",
        "answer_format",
        "idempotency_key",
    } <= _params(sessions.create_session)
    assert {"owner", "status", "agent", "group_id", "parent_session_id", "search", "page", "size"} <= _params(
        sessions.list_sessions
    )
    assert "request" in _params(sessions.send_session_messages)
    for method in [
        "get_session",
        "get_session_status",
        "get_session_changes",
        "get_session_resource",
        "list_session_events",
        "cancel_session",
        "pause_session",
        "resume_session",
        "force_session_answer",
        "submit_session_feedback",
        "submit_event_feedback",
        "share_session",
        "unshare_session",
        "get_session_quota",
    ]:
        assert hasattr(sessions, method), f"sessions.{method} is gone."


def test_resource_method_signatures() -> None:
    client = _client()
    assert {"name", "description", "environments", "model", "instructions", "subagents", "skills"} <= _params(
        client.agents.create_agent
    )
    assert {"name", "description", "body", "source", "url_pattern"} <= _params(client.skills.create_skill)
    assert "request" in _params(client.environments.create_environment)
    assert "request" in _params(client.environments.update_environment)


def test_request_bodies_construct() -> None:
    msg = hai_agents.SendSessionMessagesRequestBody_UserMessage(message="hi")
    assert msg.message == "hi"
    env = hai_agents.CreateEnvironmentRequest_Web(id="e", headless=True, width=1280, height=720)
    assert env.kind == "web"


def _command_paths(command, prefix=None):
    prefix = prefix or []
    yield prefix
    for name, sub in getattr(command, "commands", {}).items():
        yield from _command_paths(sub, prefix + [name])


def test_help_renders_for_every_command() -> None:
    for path in _command_paths(get_command(app)):
        result = runner.invoke(app, path + ["--help"])
        assert result.exit_code == 0, f"`hai {' '.join(path)} --help` failed:\n{result.output}"


def test_schema_is_valid_json() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["name"] == "hai"
    names = {command["name"] for command in data["commands"]}
    assert {"session", "agent", "skill", "env", "schema", "configure"} <= names


def test_json_error_is_structured(capsys: pytest.CaptureFixture) -> None:
    Output.create(OutputMode.JSON, quiet=False, no_color=True).fail("api_error", "not found", status=404)
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == {"kind": "api_error", "message": "not found", "status": 404}

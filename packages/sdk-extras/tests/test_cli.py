from __future__ import annotations

import json
import os

from hai_agents_extras.cli import app as app_module
from hai_agents_extras.cli.app import app
from typer.testing import CliRunner

from hai_agents.polling import SessionRunResult

runner = CliRunner()


def test_help_renders_h_glyph() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "| |__| |" in result.output
    assert "hai-agents" in result.output


def test_missing_api_key_is_clear() -> None:
    result = runner.invoke(app, ["sessions", "get", "sess_1"], env={})

    assert result.exit_code != 0
    assert "No API key found" in result.output


def test_run_prints_json(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: object())
    monkeypatch.setattr(app_module.runners, "run_agent", _fake_run_agent)

    result = runner.invoke(app, ["--json", "run", "hello"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"answer": "done", "session_id": "sess_1", "status": "completed"}


def test_share_session_prints_url(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: object())
    monkeypatch.setattr(app_module.runners, "share_session", lambda client, session_id: f"/share/{session_id}")

    result = runner.invoke(app, ["sessions", "share", "sess_1"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert "/share/sess_1" in result.output


def test_mcp_command_honors_global_connection_options(monkeypatch) -> None:
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.delenv("HAI_API_BASE_URL", raising=False)
    monkeypatch.setattr(app_module.mcp_server, "run_server", lambda: None)

    result = runner.invoke(
        app,
        ["--api-key", "hk-test", "--base-url", "https://example.test", "mcp"],
        env={},
    )

    assert result.exit_code == 0, result.output
    assert os.environ["HAI_API_KEY"] == "hk-test"
    assert os.environ["HAI_API_BASE_URL"] == "https://example.test"
    assert "hk-test" not in result.output


def _fake_run_agent(client, params, *, on_event):
    return SessionRunResult(id="sess_1", status="completed", events=[], next_from_index=0, final_changes=_Answer())


class _Answer:
    answer = "done"

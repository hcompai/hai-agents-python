from __future__ import annotations

import json

from typer.testing import CliRunner

import hai_agents_cli.app as app_module
from hai_agents.polling import SessionRunResult
from hai_agents_cli.app import app

runner = CliRunner()


def test_help_renders_h_glyph() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "| |__| |" in result.output
    assert "hai" in result.output


def test_missing_api_key_is_clear(monkeypatch) -> None:
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.delenv("H_API_KEY", raising=False)

    result = runner.invoke(app, ["sessions", "get", "sess_1"], env={})

    assert result.exit_code != 0
    assert "No API key found" in _error_text(result)


def test_run_prints_json(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: object())
    monkeypatch.setattr(app_module, "run_session", _fake_run_session)

    result = runner.invoke(app, ["--json", "run", "hello"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"answer": "done", "session_id": "sess_1", "status": "completed"}


def test_share_session_prints_absolute_url(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr(app_module, "_client", lambda state: client)

    result = runner.invoke(app, ["sessions", "share", "sess_1"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert "https://agp.example.test/share/sess_1" in result.output


def test_state_missing_is_a_programming_error() -> None:
    try:
        app_module._state(type("Ctx", (), {"obj": None})())
    except RuntimeError as exc:
        assert "CLI state was not initialized" in str(exc)
    else:
        raise AssertionError("_state should fail when Typer state is missing")


def _fake_run_session(client, **kwargs):
    assert kwargs["messages"] == "hello"
    assert kwargs["agent"] == "h/web-surfer-holo3-1-35b"
    return SessionRunResult(id="sess_1", status="completed", events=[], next_from_index=0, final_changes=_Answer())


class _Answer:
    answer = "done"


class _ClientWrapper:
    def get_base_url(self) -> str:
        return "https://agp.example.test"


class _Sessions:
    def share_session(self, session_id: str):
        return type("Share", (), {"share_url": f"/share/{session_id}"})()


class _Client:
    _client_wrapper = _ClientWrapper()
    sessions = _Sessions()


def _error_text(result) -> str:
    return "\n".join(part for part in (result.output, result.stderr, str(result.exception)) if part)

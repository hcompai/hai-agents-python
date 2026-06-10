from __future__ import annotations

import json

from typer.testing import CliRunner

import hai_agents_cli.app as app_module
from hai_agents.polling import SessionRunResult
from hai_agents_cli.app import app
from hai_agents_common import credentials

runner = CliRunner()


def test_help_renders_h_glyph() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "| |__| |" in result.output
    assert "hai" in result.output


def test_missing_api_key_is_clear(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.delenv("H_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "LOCAL_ENV_PATH", tmp_path / "local.env")
    monkeypatch.setattr(credentials, "GLOBAL_ENV_PATH", tmp_path / "global.env")

    result = runner.invoke(app, ["sessions", "get", "sess_1"], env={})

    assert result.exit_code != 0
    assert "No API key found" in _error_text(result)


def test_run_prints_json(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient())
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)

    result = runner.invoke(app, ["--json", "run", "hello"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "answer": "done",
        "session_id": "sess_1",
        "status": "completed",
        "agent_view_url": "https://platform.example.test/agent-view/sess_1",
    }


def test_run_prints_live_view_link(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient())
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)

    result = runner.invoke(app, ["run", "hello"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert "https://platform.example.test/agent-view/sess_1" in result.output


def test_share_session_prints_absolute_url(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr(app_module, "_client", lambda state: client)

    result = runner.invoke(app, ["sessions", "share", "sess_1"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert "https://agp.example.test/share/sess_1" in result.output


def test_json_output_is_pipe_safe_for_long_values(monkeypatch) -> None:
    long_id = "x" * 200

    class _LongSessions:
        def share_session(self, session_id: str):
            return type("Share", (), {"share_url": f"/share/{long_id}"})()

    class _LongClient:
        _client_wrapper = _ClientWrapper()
        sessions = _LongSessions()

    monkeypatch.setattr(app_module, "_client", lambda state: _LongClient())

    result = runner.invoke(app, ["--json", "sessions", "share", "sess_1"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)  # raises if rich wrapped the value mid-string
    assert payload["share_url"].endswith(long_id)


def test_state_missing_is_a_programming_error() -> None:
    try:
        app_module._state(type("Ctx", (), {"obj": None})())
    except RuntimeError as exc:
        assert "CLI state was not initialized" in str(exc)
    else:
        raise AssertionError("_state should fail when Typer state is missing")


def test_run_rejects_oversized_payload_before_sending(monkeypatch) -> None:
    captured: dict = {}
    client = _RunClient(capture=captured)
    monkeypatch.setattr(app_module, "_client", lambda state: client)

    result = runner.invoke(app, ["run", "x" * (6 * 1024 * 1024)], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code != 0
    assert "over the" in _error_text(result)
    assert not captured  # no HTTP call was attempted


def test_run_parses_overrides(monkeypatch) -> None:
    captured: dict = {}
    client = _RunClient(capture=captured)

    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)

    result = runner.invoke(
        app,
        [
            "run",
            "hello",
            "-o",
            "agent.environments[kind=web].start_url=https://bing.com",
            "-o",
            "agent.max_steps=5",
        ],
        env={"HAI_API_KEY": "hk-test"},
    )

    assert result.exit_code == 0, result.output
    assert captured["overrides"] == {
        "agent.environments[kind=web].start_url": "https://bing.com",
        "agent.max_steps": 5,
    }


def _fake_wait_for_session(client, id, **kwargs):
    assert id == "sess_1"
    return SessionRunResult(id="sess_1", status="completed", events=[], next_from_index=0, final_changes=_Answer())


class _RunSessions:
    def __init__(self, capture: dict | None = None) -> None:
        self._capture = capture

    def create_session(self, **kwargs):
        if self._capture is not None:
            self._capture.update(kwargs)
        return type(
            "Session",
            (),
            {"id": "sess_1", "agent_view_url": "https://platform.example.test/agent-view/sess_1"},
        )()


class _RunClient:
    def __init__(self, capture: dict | None = None) -> None:
        self.sessions = _RunSessions(capture)


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

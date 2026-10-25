from __future__ import annotations

import contextlib
import json

from typer.testing import CliRunner

import hai_agents_cli.app as app_module
from hai_agents.polling import MAX_REQUEST_BYTES, SessionRunResult
from hai_agents_cli.app import app
from hai_agents_common import credentials

runner = CliRunner()


def test_help_lists_examples() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert 'holo "What is the top story on Hacker News?"' in result.output


def test_route_runs_bare_tasks_and_hoists_global_options() -> None:
    commands = {"run", "chat", "sessions", "agents", "doctor", "login"}

    def route(*argv: str, interactive: bool = True) -> list[str]:
        return app_module.route(list(argv), commands, interactive)

    assert route("top story on HN?") == ["run", "top story on HN?"]
    assert route("--local", "open calculator") == ["run", "--local", "open calculator"]
    assert route("run", "x", "--json") == ["--json", "run", "x"]
    assert route("sessions", "get", "s1", "--api-key", "k") == ["--api-key", "k", "sessions", "get", "s1"]
    assert route() == ["chat"]
    assert route(interactive=False) == []
    assert route("sesions") == ["sesions"]
    assert route("--help") == ["--help"]


def test_missing_api_key_is_clear(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "GLOBAL_ENV_PATH", tmp_path / "global.env")

    result = runner.invoke(app, ["sessions", "get", "sess_1"], env={})

    assert result.exit_code != 0
    assert "No API key found" in _error_text(result)


def test_run_prints_json(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient())
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(app, ["--json", "run", "hello", "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "answer": "done",
        "session_id": "sess_1",
        "status": "completed",
        "outcome": None,
        "error": None,
        "error_code": None,
        "agent_view_url": "https://platform.example.test/agent-view/sess_1",
    }


def test_run_failure_exits_nonzero_with_error_and_structured_answer(monkeypatch) -> None:
    failed = SessionRunResult(
        id="sess_1",
        status="failed",
        events=[],
        next_from_index=0,
        answer={"price": 42},
        error="browser crashed",
        error_code="env_error",
    )
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient())
    monkeypatch.setattr(app_module, "wait_for_session", lambda client, id, **_: failed)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(app, ["run", "hello", "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 1, result.output
    assert "browser crashed" in result.output
    assert '"price": 42' in result.output


def test_run_prints_live_view_link(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient())
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(app, ["run", "hello", "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert "https://platform.example.test/agent-view/sess_1" in result.output


def test_kill_switch_stops_that_turn_and_the_next_message_starts_a_new_session(monkeypatch, tmp_path) -> None:
    from hai_agents_local import killswitch

    monkeypatch.setattr(killswitch, "STOP_PATH", tmp_path / "stop")
    client = _RunClient()
    results = iter(
        [
            SessionRunResult(id="sess_1", status="cancelled", events=[], next_from_index=0),
            SessionRunResult(id="sess_1", status="idle", events=[], next_from_index=3, answer="ok"),
        ]
    )
    follows = iter([killswitch.request_stop, lambda: None])
    replies = iter(["open it again", None])
    monkeypatch.setattr(app_module, "_local_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", lambda client_, id, **_: next(results))
    monkeypatch.setattr(app_module, "_follow", lambda *a, **k: next(follows)())
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_ask", lambda: next(replies))

    result = runner.invoke(app, ["run", "open calculator", "--local"], env={"HAI_API_KEY": "hk-test"})

    assert result.output.count("stopped by the kill switch") == 1
    assert client.sessions.created == 2
    assert client.sessions.sent == []


def test_follow_stops_once_the_agent_awaits_client_tools(monkeypatch) -> None:
    awaiting = {"type": "ActiveStateChangeEvent", "data": {"state": "awaiting_tool_results"}}

    def stream(*args, **kwargs):
        yield awaiting
        raise AssertionError("kept streaming past awaiting_tool_results")

    handled: list = []
    monkeypatch.setattr(app_module, "stream_session", stream)
    app_module._follow(None, "sess_1", type("Feed", (), {"handle": lambda self, e: handled.append(e)})(), timeout_s=1)

    assert handled == [awaiting]


def test_local_run_hands_the_api_key_flag_to_the_runtime(monkeypatch) -> None:
    import hai_agents

    captured: dict = {}
    monkeypatch.setattr(hai_agents.Client, "local", classmethod(lambda cls, **kw: captured.update(kw) or _RunClient()))
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    runner.invoke(app, ["--api-key", "hk-flag", "run", "open calculator", "--local"])

    assert captured["local_options"]["spawn_env"]["HAI_API_KEY"] == "hk-flag"


def test_run_without_agent_uses_the_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(credentials, "GLOBAL_ENV_PATH", tmp_path / "global.env")
    monkeypatch.delenv(credentials.AGENT_VAR, raising=False)
    captured: dict = {}
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient(capture=captured))
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(app, ["run", "hello"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert captured["agent"] == "h/web-surfer-flash"
    assert "idle_timeout_s" not in captured

    credentials.save_default_agent("h/web-surfer-pro")
    runner.invoke(app, ["run", "hello"], env={"HAI_API_KEY": "hk-test"})
    assert captured["agent"] == "h/web-surfer-pro"


def test_follow_up_continues_the_same_session_from_the_last_event(monkeypatch) -> None:
    captured: dict = {}
    client = _RunClient(capture=captured)
    waits: list[int] = []

    def wait(client_, id, *, from_index=0, **_):
        waits.append(from_index)
        return SessionRunResult(id=id, status="idle", events=[], next_from_index=from_index + 7, answer="ok")

    replies = iter(["and the second one?", None])
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", wait)
    monkeypatch.setattr(app_module, "_follow", _no_events)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_ask", lambda: next(replies))

    result = runner.invoke(app, ["run", "top story?"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert captured["idle_timeout_s"] == app_module.IDLE_TIMEOUT_S
    assert client.sessions.created == 1
    assert client.sessions.sent == [("sess_1", "and the second one?")]
    assert waits == [0, 7]


def test_esc_waits_for_the_pause_then_sends_the_correction_and_resumes(monkeypatch) -> None:
    monkeypatch.setattr(app_module.time, "sleep", lambda s: None)
    for typed, expected in (("only the top 2", [("send", "only the top 2"), ("resume",)]), ("", [("resume",)])):
        client = _RunClient()
        convo = app_module._Conversation(
            app_module.AppState(api_key=None, base_url=None, json_output=False),
            "h/test-agent",
            local=False,
            max_steps=5,
            max_time_s=60,
            overrides={},
            client=client,
            session=type("Session", (), {"id": "sess_1"})(),
        )
        monkeypatch.setattr(app_module, "_ask", lambda typed=typed: typed)

        convo._steer(_Watcher())

        assert client.sessions.calls == [("pause",), *expected]


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

    result = runner.invoke(
        app, ["run", "x" * (MAX_REQUEST_BYTES + 1), "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"}
    )

    assert result.exit_code != 0
    assert "over the" in _error_text(result)
    assert not captured  # no HTTP call was attempted


def test_run_validates_payload_before_agent_selection(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient())

    result = runner.invoke(app, ["run", "x" * (MAX_REQUEST_BYTES + 1)], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code != 0
    assert "over the" in _error_text(result)


def test_run_parses_overrides(monkeypatch) -> None:
    captured: dict = {}
    client = _RunClient(capture=captured)

    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(
        app,
        [
            "run",
            "hello",
            "-a",
            "h/test-agent",
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


def _no_events(client, session_id, feed, **_) -> None:
    return None


def _fake_wait_for_session(client, id, **kwargs):
    assert id == "sess_1"
    return SessionRunResult(id="sess_1", status="completed", events=[], next_from_index=0, final_changes=_Answer())


class _RunSessions:
    def __init__(self, capture: dict | None = None) -> None:
        self._capture = capture
        self.created = 0
        self.sent: list[tuple[str, str]] = []
        self.calls: list[tuple] = []

    def create_session(self, **kwargs):
        self.created += 1
        if self._capture is not None:
            self._capture.update(kwargs)
        return type(
            "Session",
            (),
            {"id": "sess_1", "agent_view_url": "https://platform.example.test/agent-view/sess_1"},
        )()

    def send_session_messages(self, id, *, request):
        self.sent.append((id, request.message))
        self.calls.append(("send", request.message))

    def pause_session(self, id):
        self.calls.append(("pause",))
        self._polls_until_paused = 2

    def get_session_status(self, id):
        self._polls_until_paused -= 1
        return type("Status", (), {"status": "paused" if self._polls_until_paused <= 0 else "running"})()

    def resume_session(self, id):
        self.calls.append(("resume",))


class _Watcher:
    @contextlib.contextmanager
    def cooked(self):
        yield


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

from __future__ import annotations

import concurrent.futures
import contextlib
import io
import json
import os
import types
from datetime import datetime, timezone

import pytest
from rich.console import Console
from typer.testing import CliRunner

import hai_agents_cli.app as app_module
from hai_agents.core.api_error import ApiError
from hai_agents.polling import MAX_REQUEST_BYTES, SessionRunResult
from hai_agents_cli import steer, ui
from hai_agents_cli.app import app
from hai_agents_common import credentials

runner = CliRunner()


def test_help_lists_examples() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert 'holo "What is the top story on Hacker News?"' in result.output


@pytest.mark.parametrize(
    ("body", "fix"),
    [
        (
            {"message": "not public", "detail": [{"type": "environment_not_public", "message": "not public"}]},
            "agents-api/your-desktop",
        ),
        ({"detail": "Forbidden"}, "holo login --force"),
    ],
)
def test_a_403_hints_at_its_cause(monkeypatch, body: dict, fix: str) -> None:
    def get_agent(*_a, **_k):
        raise ApiError(status_code=403, body=body)

    client = types.SimpleNamespace(agents=types.SimpleNamespace(get_agent=get_agent))
    monkeypatch.setattr(app_module, "_client", lambda state: client)

    result = runner.invoke(app, ["agents", "get", "h/holo-desktop", "--resolve"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 1
    assert fix in " ".join(result.output.split())


def test_route_runs_bare_tasks_and_hoists_global_options() -> None:
    commands = {"run", "chat", "sessions", "agents", "doctor", "login"}

    def route(*argv: str, interactive: bool = True) -> list[str]:
        return app_module.route(list(argv), commands, interactive)

    assert route("top story on HN?") == ["run", "top story on HN?"]
    assert route("--local", "open calculator") == ["run", "--local", "open calculator"]
    assert route("run", "x", "--json") == ["--json", "run", "x"]
    assert route("sessions", "get", "s1", "--api-key", "k") == ["--api-key", "k", "sessions", "get", "s1"]
    assert route() == ["chat"]
    assert route("--local") == ["chat", "--local"]
    assert route("-a", "h/web-surfer-pro") == ["chat", "-a", "h/web-surfer-pro"]
    assert route("--local", interactive=False) == ["run", "--local"]
    assert route(interactive=False) == []
    assert route("sesions") == ["sesions"]
    assert route("guard") == ["guard"]
    assert route("open", "calculator") == ["run", "open", "calculator"]
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
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "_local_kinds", lambda client_, agent: ["desktop"])
    monkeypatch.setattr(app_module, "wait_for_session", lambda client_, id, **_: next(results))
    monkeypatch.setattr(app_module, "_follow", lambda *a, **k: next(follows)())
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    result = runner.invoke(app, ["run", "open calculator", "-a", "h/holo-desktop"], env={"HAI_API_KEY": "hk-test"})

    assert result.output.count("stopped by the kill switch") == 1
    assert client.sessions.created == 2
    assert client.sessions.sent == []


def test_a_client_tool_wait_ends_the_session_and_the_next_message_starts_a_new_one(monkeypatch) -> None:
    client = _RunClient()
    results = iter(
        [
            SessionRunResult(id="sess_1", status="awaiting_tool_results", events=[], next_from_index=0),
            SessionRunResult(id="sess_1", status="idle", events=[], next_from_index=3, answer="ok"),
        ]
    )
    replies = iter(["try again", None])
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", lambda client_, id, **_: next(results))
    monkeypatch.setattr(app_module, "_follow", _no_events)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    result = runner.invoke(app, ["run", "use my tool", "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert client.sessions.created == 2
    assert client.sessions.sent == []
    assert ("cancel",) in client.sessions.calls


@pytest.mark.parametrize("earlier", [[], ["completed"]], ids=["first turn", "after a finished session"])
def test_a_lost_stream_keeps_the_session_for_the_next_message(monkeypatch, earlier) -> None:
    client = _RunClient()
    finished = [SessionRunResult(id="sess_1", status=status, events=[], next_from_index=1) for status in earlier]
    idle = SessionRunResult(id="sess_1", status="idle", events=[], next_from_index=1)
    results = iter([*finished, RuntimeError("stream lost"), idle])

    def wait(client_, id, **_):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    replies = iter([*(["next task"] * len(earlier)), "try again", None])
    streamed_from = []

    def follow(client_, session_id, feed, *, from_index, **_):
        streamed_from.append(from_index)
        for _ in range(2):
            feed.handle({"type": "AgentEvent", "data": {"kind": "message_event", "caller_id": "agent", "content": []}})

    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", wait)
    monkeypatch.setattr(app_module, "_follow", follow)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    result = runner.invoke(app, ["run", "find flights", "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert "lost the session's stream" in result.output
    assert client.sessions.created == 1 + len(earlier)
    assert client.sessions.calls == [("send", "try again")]
    assert streamed_from[-2:] == [0, 2]


def test_retry_runs_the_first_task_again_in_a_new_session(monkeypatch) -> None:
    captured: dict = {}
    client = _RunClient(capture=captured)
    idle = SessionRunResult(id="sess_1", status="idle", events=[], next_from_index=1)
    replies = iter(["only direct ones", "/retry", None])
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", lambda *a, **k: idle)
    monkeypatch.setattr(app_module, "_follow", _no_events)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    result = runner.invoke(app, ["run", "find flights", "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert client.sessions.created == 2
    assert "find flights" in json.dumps(captured["messages"], default=str)
    assert ("cancel",) in client.sessions.calls


def test_ctrl_c_while_starting_cancels_the_new_session_and_the_chat_continues(monkeypatch) -> None:
    client = _RunClient()

    class InterruptedFuture(concurrent.futures.Future):
        def result(self, timeout=None):
            if not self.done():
                raise KeyboardInterrupt
            return super().result(timeout)

    class Pool:
        def __init__(self, **_) -> None:
            self.jobs: list = []

        def __enter__(self):
            return self

        def __exit__(self, *_) -> None:
            for future, call, kwargs in self.jobs:
                future.set_result(call(**kwargs))

        def submit(self, call, **kwargs):
            future = InterruptedFuture()
            self.jobs.append((future, call, kwargs))
            return future

    replies = iter([None])
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module.concurrent.futures, "ThreadPoolExecutor", Pool)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    result = runner.invoke(app, ["run", "find flights", "-a", "h/test-agent"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert client.sessions.calls == [("cancel",)]


def test_a_turn_stops_following_at_a_client_tool_wait_but_watch_does_not(monkeypatch) -> None:
    awaiting = {"type": "ActiveStateChangeEvent", "data": {"state": "awaiting_tool_results"}}
    answered = {"type": "ActiveStateChangeEvent", "data": {"state": "running"}}
    monkeypatch.setattr(app_module, "stream_session", lambda *a, **k: iter([awaiting, answered]))

    for stop_at_tool_wait, expected in ((True, [awaiting]), (False, [awaiting, answered])):
        handled: list = []
        feed = type("Feed", (), {"handle": lambda self, e: handled.append(e)})()
        app_module._follow(None, "sess_1", feed, timeout_s=1, stop_at_tool_wait=stop_at_tool_wait)
        assert handled == expected


def test_a_follow_up_after_a_failed_turn_starts_a_new_session(monkeypatch) -> None:
    client = _RunClient()
    failed = SessionRunResult(id="sess_1", status="failed", events=[], next_from_index=1)
    replies = iter(["try again", None])
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", lambda *a, **k: failed)
    monkeypatch.setattr(app_module, "_follow", _no_events)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    runner.invoke(app, ["run", "first task"], env={"HAI_API_KEY": "hk-test"})

    assert client.sessions.created == 2
    assert client.sessions.sent == []


def test_local_runs_any_agent_inline_on_the_local_runtime(monkeypatch) -> None:
    captured: dict = {}
    cloud, runtime = _RunClient(), _RunClient(captured)
    fetched: list = []
    spec = types.SimpleNamespace(model_dump=lambda **_: {"name": "h/web-surfer-pro", "instructions": "Browse."})
    cloud.agents = types.SimpleNamespace(get_agent=lambda *a, **kw: fetched.append((a, kw)) or spec)
    monkeypatch.setattr(app_module, "_client", lambda state: cloud)
    monkeypatch.setattr(app_module, "_local_client", lambda state: runtime)
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(app, ["run", "x", "--local", "-a", "h/web-surfer-pro"], env={"HAI_API_KEY": "hk-t"})

    assert result.exit_code == 0, result.output
    assert fetched == [(("h/web-surfer-pro",), {"revision": None, "resolve": True})]
    assert captured["agent"] == {"name": "h/web-surfer-pro", "instructions": "Browse."}
    assert cloud.sessions.created == 0


def test_new_releases_the_idle_session_before_starting_another(monkeypatch) -> None:
    client = _RunClient()
    idle = SessionRunResult(id="sess_1", status="idle", events=[], next_from_index=1, answer="ok")
    replies = iter(["/new", "second task", None])
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", lambda *a, **k: idle)
    monkeypatch.setattr(app_module, "_follow", _no_events)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    result = runner.invoke(app, ["run", "first task"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert client.sessions.calls == [("cancel",)]
    assert client.sessions.created == 2


def test_run_without_options_uses_the_default_agent_uncapped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(credentials, "GLOBAL_ENV_PATH", tmp_path / "global.env")
    monkeypatch.setenv(credentials.AGENT_VAR, "")
    monkeypatch.delenv(credentials.AGENT_VAR)
    captured: dict = {}
    monkeypatch.setattr(app_module, "_client", lambda state: _RunClient(capture=captured))
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(app, ["run", "hello"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert captured["agent"] == "h/web-surfer-flash"
    assert not {"idle_timeout_s", "max_steps", "max_time_s"} & captured.keys()

    credentials.save_default_agent("h/web-surfer-pro")
    runner.invoke(app, ["run", "hello"], env={"HAI_API_KEY": "hk-test"})
    assert captured["agent"] == "h/web-surfer-pro"


def test_every_run_adds_the_users_holo_dir_to_its_agent(monkeypatch, holo_home) -> None:
    skill = holo_home / "skills" / "expenses"
    skill.mkdir(parents=True)
    (holo_home / "agents.md").write_text("Call me Alex.")
    (skill / "SKILL.md").write_text("---\nname: Expenses\ndescription: File my receipts.\n---\nOpen the portal.")
    captured: dict = {}
    client = _RunClient(captured)
    fetched: list = []
    spec = types.SimpleNamespace(model_dump=lambda **_: {"instructions": "Be brief.", "skills": ["h/web"]})
    client.agents = types.SimpleNamespace(
        get_agent=lambda name, revision, resolve: fetched.append((name, revision)) or spec
    )
    monkeypatch.setattr(app_module, "_client", lambda state: client)
    monkeypatch.setattr(app_module, "wait_for_session", _fake_wait_for_session)
    monkeypatch.setattr(app_module, "_follow", _no_events)

    result = runner.invoke(app, ["run", "hi", "-a", "me/helper:3"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert fetched == [("me/helper", 3)]
    assert captured["overrides"] == {
        "agent.instructions": "Be brief.\n\nCall me Alex.",
        "agent.skills": ["h/web", {"name": "expenses", "description": "File my receipts.", "body": "Open the portal."}],
    }
    (skill / "SKILL.md").write_text("no frontmatter")
    broken = runner.invoke(app, ["run", "hi"], env={"HAI_API_KEY": "hk-test"})
    assert "needs YAML frontmatter with a description" in " ".join(_error_text(broken).split())


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
    monkeypatch.setattr(app_module, "_read_message", lambda convo: next(replies))

    result = runner.invoke(app, ["run", "top story?"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert captured["idle_timeout_s"] == app_module.IDLE_TIMEOUT_S
    assert client.sessions.created == 1
    assert client.sessions.sent == [("sess_1", "and the second one?")]
    assert waits == [0, 7]


def _steering(client) -> steer.Steering:
    feed = ui.StepFeed(Console(file=io.StringIO()))
    return steer.Steering(client, "sess_1", feed, feed.out, spawn=lambda work: work())


@pytest.mark.parametrize(
    ("keys", "send_fails", "calls"),
    [
        (["only the top 2\r"], False, [("pause",), ("send", "only the top 2"), ("resume",)]),
        ([None, "only the top 2\r"], False, [("pause",), ("send", "only the top 2"), ("resume",)]),
        ([None, None], False, [("pause",), ("resume",)]),
        (["/answer\r"], False, [("pause",), ("answer",)]),
        (["only the top 2\r"], True, [("pause",), ("resume",)]),
        ([None, "end"], False, [("pause",), ("resume",)]),
    ],
    ids=["typed while it works", "esc, then a message", "esc twice", "/answer", "send fails", "stream ends paused"],
)
def test_a_message_waits_for_the_pause_so_the_agent_cannot_answer_past_it(monkeypatch, keys, send_fails, calls):
    monkeypatch.setattr(steer.time, "sleep", lambda s: None)
    client = _RunClient()
    client.sessions.send_fails = send_fails
    steering = _steering(client)
    for typed in keys:
        if typed is None:
            steering.on_esc()
        elif typed == "end":
            steering.finish()
        else:
            steering.on_keys(typed)

    assert (client.sessions.calls, steering.pending) == (calls, None)


def test_a_cancel_leaves_the_session_alone_while_a_pause_is_in_flight(monkeypatch) -> None:
    monkeypatch.setattr(steer.time, "sleep", lambda s: None)
    client = _RunClient()
    feed = ui.StepFeed(Console(file=io.StringIO()))
    in_flight: list = []
    steering = steer.Steering(client, "sess_1", feed, feed.out, spawn=in_flight.append)
    steering.on_keys("only the top 2\r")
    steering.stop()
    steering.finish()
    in_flight[0]()

    assert client.sessions.calls == [("pause",)]


def test_a_message_after_the_stream_ends_is_the_next_turn() -> None:
    client = _RunClient()
    steering = _steering(client)
    steering.finish()
    steering.on_keys("only the top 2\r")

    assert (client.sessions.calls, steering.pending, steering.pending_shown) == ([], "only the top 2", False)


@pytest.mark.parametrize(
    ("statuses", "expected", "pending"),
    [
        (["pending", "running", "paused"], [("pause",), ("send", "only the top 2"), ("resume",)], None),
        ([RuntimeError("network down")], [("send", "only the top 2")], None),
        (["running", "idle"], [("pause",), ("resume",)], "only the top 2"),
        (["running", "completed"], [("pause",)], "only the top 2"),
    ],
    ids=[
        "booting, so the pause waits for the run",
        "status unknown",
        "idle, so a queued pause would freeze its next run",
        "ended",
    ],
)
def test_a_message_lands_even_when_the_pause_cannot(monkeypatch, statuses, expected, pending) -> None:
    monkeypatch.setattr(steer.time, "sleep", lambda s: None)
    replies = iter(statuses)

    def get_session_status(id):
        status = next(replies, statuses[-1])
        if isinstance(status, Exception):
            raise status
        return type("Status", (), {"status": status})()

    client = _RunClient()
    client.sessions.get_session_status = get_session_status
    steering = _steering(client)
    steering.on_keys("only the top 2\r")

    assert (client.sessions.calls, steering.pending) == (expected, pending)


def test_agent_numbers_follow_the_listed_order_h_agents_first(monkeypatch) -> None:
    agent = lambda name: type("Agent", (), {"name": name, "description": ""})()  # noqa: E731
    client = type("Client", (), {})()
    client.agents = type("Agents", (), {})()
    client.agents.list_agents = lambda **_: type("Page", (), {"items": [agent("mine"), agent("h/surfer")]})()
    shown: list = []
    monkeypatch.setattr("hai_agents_cli.prompt.choose", lambda rows, headers, current: shown.append(rows) or 1)

    assert app_module._pick_agent(client) == "mine"
    assert [name for name, _ in shown[0]] == ["h/surfer", "mine"]


def test_resume_switches_sessions_but_keeps_the_current_one_when_picked_again() -> None:
    summary = lambda id: types.SimpleNamespace(  # noqa: E731
        id=id,
        agent=None,
        status="idle",
        first_message=None,
        last_activity_at=None,
        created_at=datetime.now(timezone.utc),
        agent_view_url=None,
    )
    on_device = {"environments": [{"kind": "desktop", "host": "user_device", "session_id": "bridge_1"}]}
    agents = {"sess_3": on_device}
    metrics = {"type": "MetricsUpdateEvent", "data": {"metrics": {"steps": 4, "total_cost": 0.12}}}
    client = _RunClient()
    client.sessions.list_sessions = lambda **_: types.SimpleNamespace(
        items=[summary("sess_2"), summary("sess_1"), summary("sess_3")]
    )
    client.sessions.get_session = lambda id: types.SimpleNamespace(
        id=id, latest_answer=None, agent_view_url=None, request=types.SimpleNamespace(agent=agents.get(id, "h/x"))
    )
    client.sessions.get_session_changes = lambda id, **_: types.SimpleNamespace(first_index=0, new_events=[metrics])
    convo = app_module._Conversation(
        app_module.AppState(api_key=None, base_url=None, json_output=False),
        "h/test-agent",
        max_steps=5,
        max_time_s=60,
        overrides={},
        client=client,
        session=types.SimpleNamespace(id="sess_1"),
    )

    convo.command("/resume 2")
    assert (convo.session.id, client.sessions.calls) == ("sess_1", [])

    convo.command("/resume 1")
    assert (convo.session.id, convo.next_index, client.sessions.calls) == ("sess_2", 1, [("cancel",)])
    assert (convo.steps, convo.cost) == (4, 0.12)

    convo.command("/resume 3")
    assert convo.session.id == "sess_2"


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
        self.send_fails = False
        self._polls_until_paused = 1_000

    def bridged_kinds(self, session_id):
        return []

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
        if self.send_fails:
            raise RuntimeError("network down")
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

    def force_session_answer(self, id):
        self.calls.append(("answer",))

    def cancel_session(self, id):
        self.calls.append(("cancel",))


class _RunClient:
    def __init__(self, capture: dict | None = None) -> None:
        self.sessions = _RunSessions(capture)

    def close(self) -> None:
        pass


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

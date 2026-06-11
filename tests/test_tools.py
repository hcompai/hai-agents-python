"""Custom tool schema derivation and the dispatch loop, offline."""

import asyncio
from types import SimpleNamespace

import pytest

from hai_agents import Tool, tool
from hai_agents.polling import _attach_tool_definitions, _execute_tool_call, run_session, wait_for_session


@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city."""
    return f"Sunny in {city} ({unit})"


def test_tool_decorator_derives_schema():
    assert isinstance(get_weather, Tool)
    assert get_weather.name == "get_weather"
    assert get_weather.description == "Get the current weather for a city."
    schema = get_weather.input_schema
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"city", "unit"}
    assert schema["required"] == ["city"]
    assert get_weather(city="Paris") == "Sunny in Paris (celsius)"


def test_tool_decorator_with_args_returns_tool_and_applies_overrides():
    # Both call forms must produce a Tool — the @typing.overload pair on tool() pins this contract
    # for static checkers too (a bare ``-> Any`` return makes every @tool function untyped under
    # mypy --strict's untyped-decorator rule).
    @tool(name="weather_lookup", description="Look up the weather.")
    def whatever(city: str) -> str:
        return city

    assert isinstance(whatever, Tool)
    assert whatever.name == "weather_lookup"
    assert whatever.description == "Look up the weather."


def test_tool_without_description_raises():
    with pytest.raises(ValueError, match="needs a description"):

        @tool
        def nameless(x: int) -> int:
            return x


def test_attach_definitions_string_agent_uses_overrides():
    params = {"agent": "h/researcher"}
    _attach_tool_definitions(params, [get_weather])
    assert params["agent"] == "h/researcher"
    assert params["overrides"]["agent.tools"] == [get_weather.definition()]


def test_attach_definitions_inline_agent_uses_overrides():
    agent = {"name": "mine", "description": "d", "environments": []}
    params = {"agent": dict(agent)}
    _attach_tool_definitions(params, [get_weather])
    assert params["agent"] == agent
    assert params["overrides"]["agent.tools"] == [get_weather.definition()]


class _FakeHttpx:
    def __init__(self, statuses=None):
        self.requests = []
        self._statuses = list(statuses or [])

    def request(self, path, *, method, json=None, headers=None, request_options=None):
        self.requests.append({"path": path, "method": method, "json": json, "request_options": request_options})
        status = self._statuses.pop(0) if self._statuses else 202
        return SimpleNamespace(status_code=status, headers={}, text="")


class _FakeSessions:
    def __init__(self, polls):
        self._polls = list(polls)
        self.created_with = None

    def create_session(self, **kwargs):
        self.created_with = kwargs
        return SimpleNamespace(id="sess_1")

    def get_session_changes(self, id, *, from_index, limit, include_events, wait_for_seconds):
        return self._polls[0][0] if self._polls else None

    def get_session_status(self, id):
        changes, status = self._polls.pop(0)
        return SimpleNamespace(status=status)


def _awaiting_changes(*calls):
    event = SimpleNamespace(
        type="ActiveStateChangeEvent",
        data={"state": "awaiting_tool_results", "pending_tool_calls": list(calls)},
    )
    return SimpleNamespace(new_events=[event], answer=None)


def test_run_session_dispatches_pending_calls_and_posts_results():
    sessions = _FakeSessions(
        polls=[
            (
                _awaiting_changes({"id": "c1", "name": "get_weather", "arguments": {"city": "Paris"}}),
                "awaiting_tool_results",
            ),
            (None, "completed"),
        ]
    )
    httpx = _FakeHttpx()
    client = SimpleNamespace(sessions=sessions, _client_wrapper=SimpleNamespace(httpx_client=httpx))

    result = run_session(client, agent="h/researcher", tools=[get_weather])

    assert sessions.created_with["overrides"]["agent.tools"] == [get_weather.definition()]
    assert [r["path"] for r in httpx.requests] == ["api/v2/sessions/sess_1/tool_results"]
    assert httpx.requests[0]["json"] == {
        "type": "tool_result",
        "tool_call_id": "c1",
        "result": "Sunny in Paris (celsius)",
        "is_error": False,
    }
    assert result.status == "completed"


def test_post_accepts_409_without_retrying():
    from hai_agents.polling import _post_tool_results

    httpx = _FakeHttpx(statuses=[409])
    client = SimpleNamespace(_client_wrapper=SimpleNamespace(httpx_client=httpx))
    _post_tool_results(
        client, "sess_1", [{"type": "tool_result", "tool_call_id": "c1", "result": "", "is_error": False}]
    )
    assert len(httpx.requests) == 1
    assert httpx.requests[0]["request_options"] == {"max_retries": 0}


def test_post_retries_transient_errors():
    from hai_agents.polling import _post_tool_results

    httpx = _FakeHttpx(statuses=[500, 202])
    client = SimpleNamespace(_client_wrapper=SimpleNamespace(httpx_client=httpx))
    _post_tool_results(
        client, "sess_1", [{"type": "tool_result", "tool_call_id": "c1", "result": "", "is_error": False}]
    )
    assert len(httpx.requests) == 2


def test_dispatch_reports_tool_exceptions_as_errors():
    @tool(description="always fails")
    def broken():
        raise RuntimeError("boom")

    sessions = _FakeSessions(
        polls=[
            (_awaiting_changes({"id": "c1", "name": "broken", "arguments": {}}), "awaiting_tool_results"),
            (None, "completed"),
        ]
    )
    httpx = _FakeHttpx()
    client = SimpleNamespace(sessions=sessions, _client_wrapper=SimpleNamespace(httpx_client=httpx))

    run_session(client, agent="h/researcher", tools=[broken])

    assert httpx.requests[0]["json"] == {
        "type": "tool_result",
        "tool_call_id": "c1",
        "result": "RuntimeError: boom",
        "is_error": True,
    }


def test_sync_path_awaits_async_tools():
    @tool(description="async lookup")
    async def lookup(key: str) -> str:
        return f"value:{key}"

    sessions = _FakeSessions(
        polls=[
            (_awaiting_changes({"id": "c1", "name": "lookup", "arguments": {"key": "k"}}), "awaiting_tool_results"),
            (None, "completed"),
        ]
    )
    httpx = _FakeHttpx()
    client = SimpleNamespace(sessions=sessions, _client_wrapper=SimpleNamespace(httpx_client=httpx))

    run_session(client, agent="h/researcher", tools=[lookup])

    assert httpx.requests[0]["json"]["result"] == "value:k"
    assert httpx.requests[0]["json"]["is_error"] is False


def test_settled_and_replayed_calls_are_not_re_executed():
    stale = SimpleNamespace(
        type="ActiveStateChangeEvent",
        data={
            "state": "awaiting_tool_results",
            "pending_tool_calls": [
                {"id": "c1", "name": "get_weather", "arguments": {"city": "Paris"}},
                {"id": "c2", "name": "get_weather", "arguments": {"city": "Tokyo"}},
            ],
        },
    )
    refreshed = SimpleNamespace(
        type="ActiveStateChangeEvent",
        data={
            "state": "awaiting_tool_results",
            "pending_tool_calls": [{"id": "c2", "name": "get_weather", "arguments": {"city": "Tokyo"}}],
        },
    )
    changes = SimpleNamespace(new_events=[stale, refreshed], answer=None)
    sessions = _FakeSessions(polls=[(changes, "awaiting_tool_results"), (None, "completed")])
    httpx = _FakeHttpx()
    client = SimpleNamespace(sessions=sessions, _client_wrapper=SimpleNamespace(httpx_client=httpx))

    run_session(client, agent="h/researcher", tools=[get_weather])

    assert len(httpx.requests) == 1
    assert httpx.requests[0]["json"]["tool_call_id"] == "c2"


def test_async_tool_dispatch_inside_running_loop():
    @tool(description="async lookup")
    async def lookup(key: str) -> str:
        return f"value:{key}"

    async def main():
        return _execute_tool_call({"lookup": lookup}, {"id": "c1", "name": "lookup", "arguments": {"key": "k"}})

    payload = asyncio.run(main())
    assert payload == {"type": "tool_result", "tool_call_id": "c1", "result": "value:k", "is_error": False}


def test_wait_joining_past_advertisement_recovers_pending():
    class _MidStreamSessions:
        def __init__(self):
            self._statuses = ["awaiting_tool_results", "completed"]

        def get_session_changes(self, id, *, from_index, limit, include_events, wait_for_seconds):
            if from_index == 0:
                return _awaiting_changes({"id": "c1", "name": "get_weather", "arguments": {"city": "Paris"}})
            return None

        def get_session_status(self, id):
            return SimpleNamespace(status=self._statuses.pop(0))

    httpx = _FakeHttpx()
    client = SimpleNamespace(sessions=_MidStreamSessions(), _client_wrapper=SimpleNamespace(httpx_client=httpx))

    result = wait_for_session(client, id="sess_1", from_index=9, tools=[get_weather])

    assert [r["json"]["tool_call_id"] for r in httpx.requests] == ["c1"]
    assert result.status == "completed"


def test_no_dispatch_when_status_left_awaiting():
    resumed = SimpleNamespace(
        type="ActiveStateChangeEvent",
        data={
            "state": "awaiting_tool_results",
            "pending_tool_calls": [{"id": "c1", "name": "get_weather", "arguments": {"city": "Paris"}}],
        },
    )
    changes = SimpleNamespace(new_events=[resumed], answer=None)
    sessions = _FakeSessions(polls=[(changes, "running"), (None, "completed")])
    httpx = _FakeHttpx()
    client = SimpleNamespace(sessions=sessions, _client_wrapper=SimpleNamespace(httpx_client=httpx))

    run_session(client, agent="h/researcher", tools=[get_weather])

    assert httpx.requests == []

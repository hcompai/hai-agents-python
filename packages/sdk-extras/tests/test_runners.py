from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from hai_agents_extras.runners import (
    RunAgentParams,
    async_run_agent,
    cancel_session,
    get_session,
    run_agent,
    send_message,
    share_session,
)

from hai_agents.polling import SessionRunResult
from hai_agents.types import TrajectoryEvent


def test_run_agent_streams_events_and_returns_answer() -> None:
    event = _event("AgentStartedEvent")
    sessions = _SyncSessions(events=[event])
    seen = []

    result = run_agent(SimpleNamespace(sessions=sessions), RunAgentParams(task="hello"), on_event=seen.append)

    assert result.id == "sess_1"
    assert result.status == "completed"
    assert result.answer == "done"
    assert seen == [event]
    assert sessions.created == {
        "agent": "h/web-surfer-holo3-1-35b",
        "messages": "hello",
        "max_steps": 20,
        "max_time_s": 180.0,
    }


def test_single_call_wrappers() -> None:
    sessions = _SyncSessions(events=[])
    client = SimpleNamespace(sessions=sessions)

    assert get_session(client, "sess_1").id == "sess_1"
    cancel_session(client, "sess_1")
    send_message(client, "sess_1", "continue")
    assert share_session(client, "sess_1") == "/share/sess_1"

    assert sessions.cancelled == ["sess_1"]
    assert sessions.sent == [("sess_1", "continue")]


async def test_async_run_agent_cancels_backend_when_task_is_cancelled() -> None:
    sessions = _BlockingAsyncSessions()
    task = asyncio.create_task(
        async_run_agent(SimpleNamespace(sessions=sessions), RunAgentParams(task="slow"), on_event=_noop)
    )

    await sessions.created.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert sessions.cancelled == ["sess_async"]


def test_run_agent_params_are_closed() -> None:
    with pytest.raises(ValueError):
        RunAgentParams(task="hello", answer_format={"type": "string"})


class _SyncSessions:
    def __init__(self, events: list[TrajectoryEvent]):
        self.events = events
        self.created = None
        self.cancelled = []
        self.sent = []
        self._change_calls = 0

    def create_session(self, **kwargs):
        self.created = kwargs
        return SimpleNamespace(id="sess_1")

    def get_session_changes(self, session_id, **kwargs):
        self._change_calls += 1
        if kwargs.get("include_events") is False:
            return SimpleNamespace(new_events=[], answer="done")
        return SimpleNamespace(new_events=self.events if self._change_calls == 1 else [], answer=None)

    def get_session_status(self, session_id):
        return SimpleNamespace(status="completed")

    def get_session(self, session_id):
        return SimpleNamespace(id=session_id)

    def cancel_session(self, session_id):
        self.cancelled.append(session_id)

    def send_session_messages(self, session_id, *, request):
        self.sent.append((session_id, request.message))

    def share_session(self, session_id):
        return SimpleNamespace(share_url=f"/share/{session_id}")


class _BlockingAsyncSessions:
    def __init__(self):
        self.created = asyncio.Event()
        self.cancelled = []

    async def create_session(self, **kwargs):
        self.created.set()
        return SimpleNamespace(id="sess_async")

    async def get_session_changes(self, session_id, **kwargs):
        await asyncio.sleep(3600)

    async def get_session_status(self, session_id):
        return SimpleNamespace(status="running")

    async def cancel_session(self, session_id):
        self.cancelled.append(session_id)


async def _noop(event) -> None:
    return None


def _event(event_type: str) -> TrajectoryEvent:
    return TrajectoryEvent(type=event_type, data={}, timestamp=datetime.now(timezone.utc))

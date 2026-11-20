"""Polling stops when a session settles: terminal, or idle awaiting the next message."""

from types import SimpleNamespace

import pydantic
import pytest

from hai_agents.polling import AsyncSessionHandle, SessionHandle, SessionTimeoutError, wait_for_session
from hai_agents.types import ToolApprovalRequest, ToolRequest


class _Sessions:
    def __init__(self, statuses, answer=None):
        self._statuses = list(statuses)
        self._answer = answer

    def get_session_changes(self, id, *, from_index, limit, include_events, wait_for_seconds):
        return SimpleNamespace(new_events=[], answer=self._answer)

    def get_session_status(self, id):
        return SimpleNamespace(status=self._statuses.pop(0), outcome=None, error=None, error_code=None)


def test_wait_stops_on_idle_and_returns_answer():
    client = SimpleNamespace(sessions=_Sessions(["running", "idle"], answer="done"))
    result = wait_for_session(client, "sess_1", wait_for_seconds=0)
    assert result.status == "idle"
    assert result.answer == "done"


class _Answer(pydantic.BaseModel):
    text: str


def test_idle_answer_parses_into_schema():
    client = SimpleNamespace(sessions=_Sessions(["idle"], answer='{"text": "hi"}'))
    result = wait_for_session(client, "sess_1", wait_for_seconds=0, answer_schema=_Answer)
    assert result.answer == _Answer(text="hi")


def test_idle_without_answer_returns_none_despite_schema():
    client = SimpleNamespace(sessions=_Sessions(["idle"], answer=None))
    result = wait_for_session(client, "sess_1", wait_for_seconds=0, answer_schema=_Answer)
    assert result.answer is None


class _Held:
    """Holds call_1 at step 0 until the agent picks up its decision, then a later step holds the same id."""

    def __init__(self):
        self._steps = [0, 0, 1]
        self.read = []

    def request(self, path, **_):
        return SimpleNamespace(status_code=202)

    def get_session_changes(self, id, **_):
        return None

    def get_session_status(self, id):
        self.read.append(self._steps.pop(0))
        return SimpleNamespace(
            status="awaiting_tool_results",
            steps=self.read[-1],
            pending_approvals=[
                ToolApprovalRequest(tool_req=ToolRequest(id="call_1", tool_name="shell"), requirements=[])
            ],
            pending_tool_calls=[],
            outcome=None,
            error=None,
            error_code=None,
        )


class _AsyncHeld(_Held):
    async def request(self, path, **_):
        return super().request(path)

    async def get_session_changes(self, id, **_):
        return super().get_session_changes(id)

    async def get_session_status(self, id):
        return super().get_session_status(id)


def _client(fake):
    return SimpleNamespace(sessions=fake, _client_wrapper=SimpleNamespace(httpx_client=fake))


async def test_a_wait_after_a_decision_skips_the_decided_hold_only():
    held, async_held = _Held(), _AsyncHeld()
    handle, async_handle = SessionHandle(_client(held), "sess_1"), AsyncSessionHandle(_client(async_held), "sess_1")

    handle.wait_for_completion(wait_for_seconds=0)
    handle.approve("call_1")
    handle.wait_for_completion(wait_for_seconds=0)
    await async_handle.wait_for_completion(wait_for_seconds=0)
    await async_handle.deny("call_1")
    await async_handle.wait_for_completion(wait_for_seconds=0)

    assert held.read == async_held.read == [0, 0, 1]


class _Log:
    def __init__(self):
        self.events = []
        self.status = "idle"

    def append(self, *names):
        self.events.extend(SimpleNamespace(type="MessageEvent", data={"name": name}) for name in names)

    def get_session_changes(self, id, *, from_index, limit, include_events, wait_for_seconds):
        if from_index >= len(self.events):
            assert wait_for_seconds == 0, "long-polled past the end of a settled session"
            return None
        return SimpleNamespace(new_events=self.events[from_index:], first_index=from_index, answer=None)

    def get_session_status(self, id):
        return SimpleNamespace(status=self.status, outcome=None, error=None, error_code=None)


def test_handle_resumes_each_turn_from_its_cursor():
    log = _Log()
    handle = SessionHandle(SimpleNamespace(sessions=log), "sess_1")

    def names(events):
        return [event.data["name"] for event in events]

    log.append("turn1-a", "turn1-b")
    assert names(handle.wait_for_completion().events) == ["turn1-a", "turn1-b"]
    log.append("turn2")
    assert names(handle.stream()) == ["turn2"]
    assert handle.wait_for_completion().events == []
    log.append("turn3")
    assert names(handle.wait_for_completion().events) == ["turn3"]
    assert names(handle.wait_for_completion(from_index=0).events) == [
        "turn1-a",
        "turn1-b",
        "turn2",
        "turn3",
    ]


def test_handle_resumes_after_a_timed_out_wait():
    log = _Log()
    handle = SessionHandle(SimpleNamespace(sessions=log), "sess_1")
    log.append("read-before-timeout")
    log.status = "running"
    with pytest.raises(SessionTimeoutError):
        handle.wait_for_completion(max_polls=1)
    log.append("after-timeout")
    log.status = "idle"
    assert [event.data["name"] for event in handle.wait_for_completion().events] == ["after-timeout"]

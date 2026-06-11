"""Polling stops when a session settles: terminal, or idle awaiting the next message."""

from types import SimpleNamespace

import pydantic

from hai_agents.polling import wait_for_session


class _Sessions:
    def __init__(self, statuses, answer=None):
        self._statuses = list(statuses)
        self._answer = answer

    def get_session_changes(self, id, *, from_index, limit, include_events, wait_for_seconds):
        return SimpleNamespace(new_events=[], answer=self._answer)

    def get_session_status(self, id):
        return SimpleNamespace(status=self._statuses.pop(0))


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

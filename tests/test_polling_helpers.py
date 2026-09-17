"""Unit tests for polling guards: settled vs terminal, payload size, wait timeouts.

``wait_for_session`` already has idle/schema coverage in ``test_settle.py``. These
tests lock the remaining public helpers without changing the implementation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pydantic
import pytest

from hai_agents.polling import (
    MAX_REQUEST_BYTES,
    assert_request_under_limit,
    is_settled_session_status,
    is_terminal_session_status,
    wait_for_session,
)

TERMINAL = ("completed", "failed", "timed_out", "interrupted")
IN_FLIGHT = ("queued", "pending", "running", "paused", "awaiting_tool_results")


class _AlwaysRunning:
    def get_session_changes(self, id, *, from_index, limit, include_events, wait_for_seconds):
        return SimpleNamespace(new_events=[], answer=None)

    def get_session_status(self, id):
        return SimpleNamespace(status="running", outcome=None, error=None, error_code=None)


class _Sessions:
    def __init__(self, statuses):
        self._statuses = list(statuses)

    def get_session_changes(self, id, *, from_index, limit, include_events, wait_for_seconds):
        return SimpleNamespace(new_events=[], answer="done")

    def get_session_status(self, id):
        return SimpleNamespace(status=self._statuses.pop(0), outcome=None, error=None, error_code=None)


@pytest.mark.parametrize("status", TERMINAL)
def test_terminal_statuses_are_settled_and_terminal(status: str) -> None:
    assert is_terminal_session_status(status) is True
    assert is_settled_session_status(status) is True


def test_idle_is_settled_but_not_terminal() -> None:
    assert is_terminal_session_status("idle") is False
    assert is_settled_session_status("idle") is True


@pytest.mark.parametrize("status", IN_FLIGHT)
def test_in_flight_statuses_are_neither_settled_nor_terminal(status: str) -> None:
    assert is_terminal_session_status(status) is False
    assert is_settled_session_status(status) is False


def test_payload_under_limit_is_accepted() -> None:
    payload = {"agent": "h/web-surfer-pro", "messages": "hello"}
    assert_request_under_limit(payload)
    assert_request_under_limit(payload, max_bytes=len(json.dumps(payload).encode()))


def test_oversized_payload_raises_before_send() -> None:
    with pytest.raises(ValueError, match="over the"):
        assert_request_under_limit({"blob": "x" * 200}, max_bytes=50)


def test_payload_limit_serializes_pydantic_models() -> None:
    class Shot(pydantic.BaseModel):
        png: str

    assert_request_under_limit(Shot(png="ok"), max_bytes=200)
    with pytest.raises(ValueError, match="Downscale images"):
        assert_request_under_limit(Shot(png="x" * 200), max_bytes=50)


def test_default_limit_is_five_megabytes() -> None:
    assert MAX_REQUEST_BYTES == 5 * 1024 * 1024


def test_wait_times_out_on_wall_clock() -> None:
    client = SimpleNamespace(sessions=_AlwaysRunning())
    with pytest.raises(TimeoutError, match="did not settle within 0"):
        wait_for_session(client, "sess_1", wait_for_seconds=0, timeout_seconds=0)


def test_wait_times_out_when_max_polls_exhausted() -> None:
    client = SimpleNamespace(sessions=_AlwaysRunning())
    with pytest.raises(TimeoutError, match="max_polls=2"):
        wait_for_session(client, "sess_1", wait_for_seconds=0, max_polls=2)


def test_wait_returns_if_session_settles_before_max_polls() -> None:
    client = SimpleNamespace(sessions=_Sessions(["running", "idle"]))
    result = wait_for_session(client, "sess_1", wait_for_seconds=0, max_polls=3)
    assert result.status == "idle"
    assert result.answer == "done"

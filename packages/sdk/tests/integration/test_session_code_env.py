"""Run a one-shot session with a code environment and verify the answer.

Why a math question: the answer is unambiguous, the model finishes in 1-2
steps, and we can pattern-match the result string. The session cost stays
well under a cent.

Uses the dict-payload path (bypasses the Pydantic forward-ref gotcha — same
approach as scripts/run_session.py).
"""

from __future__ import annotations

import json
import re
import time

import pytest

from hai_agents import Client
from hai_agents.api.sessions import (
    get_session_changes as get_changes,
)
from hai_agents.api.sessions import (
    get_session_status as get_status,
)
from hai_agents.api.sessions import (
    list_session_events as list_events,
)
from hai_agents.models.session_status import SessionStatus
from hai_agents.models.trajectory_status import TrajectoryStatus

pytestmark = pytest.mark.integration

TERMINAL = {
    TrajectoryStatus.COMPLETED,
    TrajectoryStatus.FAILED,
    TrajectoryStatus.TIMED_OUT,
    TrajectoryStatus.INTERRUPTED,
    TrajectoryStatus.IDLE,
}


_PROGRESS_REQUIRED = {TrajectoryStatus.IDLE, TrajectoryStatus.COMPLETED}


def _poll_until_terminal(client: Client, session_id: str, timeout_s: float = 180.0) -> SessionStatus:
    """Poll until the session reaches a real terminal state.

    A freshly-created session can briefly report ``IDLE``/``steps=0`` between
    create and the first agent step (backend race) — treat that as still-pending
    and keep polling. Only IDLE/COMPLETED with ``steps >= 1`` (or any of the
    failure states) count as terminal.
    """
    start = time.time()
    while True:
        s = get_status.sync(client=client, id=session_id)
        progressed = s.steps >= 1 or s.error is not None
        if s.status in TERMINAL and (s.status not in _PROGRESS_REQUIRED or progressed):
            return s
        if time.time() - start > timeout_s:
            pytest.fail(
                f"session {session_id} did not reach a terminal status in "
                f"{timeout_s}s (last status: {s.status}, steps: {s.steps})"
            )
        time.sleep(2)


def test_code_env_math_session(client: Client, run_id: str, created_sessions: list) -> None:
    payload = {
        "agent": {
            "name": f"{run_id}-agent",
            "description": "Integration test agent",
            "instructions": ("You are a minimalist assistant. Reply briefly with just the requested number."),
        },
        "environments": [{"id": "code", "kind": "code"}],
        "messages": [
            {
                "type": "user_message",
                "message": "What is 17 + 25? Reply with just the number.",
            }
        ],
        "max_steps": 8,
        "max_time_s": 120.0,
        "idle_timeout_s": 30,
    }

    resp = client.get_httpx_client().post("/api/v2/sessions", json=payload, timeout=60.0)
    assert resp.status_code == 201, f"create failed: {resp.status_code} {resp.text[:500]}"
    session_id = resp.json()["id"]
    created_sessions.append(session_id)

    final = _poll_until_terminal(client, session_id)
    assert final.status in (TrajectoryStatus.COMPLETED, TrajectoryStatus.IDLE), (
        f"session ended in {final.status}; error={final.error}"
    )
    assert final.steps >= 1, "agent ended without taking any steps"
    assert final.error is None

    # Answer should contain "42" — we don't insist on exact text since the
    # agent's phrasing varies, but the digit must be present.
    ch = get_changes.sync(client=client, id=session_id).to_dict()
    answer = ch.get("answer")
    assert answer is not None, f"no answer in /changes response: {ch}"
    answer_str = answer if isinstance(answer, str) else json.dumps(answer, default=str)
    assert re.search(r"\b42\b", answer_str), f"agent did not return 42; full answer: {answer_str!r}"

    # Sanity-check the events stream is shaped as expected.
    events_page = list_events.sync(client=client, id=session_id)
    assert len(events_page.items) > 0
    event_types = {(ev.to_dict() if hasattr(ev, "to_dict") else ev).get("type") for ev in events_page.items}
    # Every healthy run has at least one AgentEvent (wraps the policy + answer).
    assert "AgentEvent" in event_types, f"no AgentEvent in events feed; saw: {sorted(event_types)}"

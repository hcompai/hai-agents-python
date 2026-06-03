"""Run a one-shot session with a code environment and verify the answer.

Why a math question: the answer is unambiguous, the model finishes in 1-2
steps, and we can pattern-match the result string. The session cost stays well
under a cent.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from hai_agents import Client, SessionStatus

pytestmark = pytest.mark.integration

TERMINAL = {"completed", "failed", "timed_out", "interrupted", "idle"}
# A freshly-created session can briefly report idle/steps=0 before the first
# step (backend race); only treat idle/completed as terminal once it progressed.
_PROGRESS_REQUIRED = {"idle", "completed"}


def _poll_until_terminal(client: Client, session_id: str, timeout_s: float = 180.0) -> SessionStatus:
    start = time.time()
    while True:
        s = client.sessions.get_session_status(session_id)
        status = str(s.status)
        progressed = (s.steps or 0) >= 1 or s.error is not None
        if status in TERMINAL and (status not in _PROGRESS_REQUIRED or progressed):
            return s
        if time.time() - start > timeout_s:
            pytest.fail(
                f"session {session_id} did not reach a terminal status in "
                f"{timeout_s}s (last status: {s.status}, steps: {s.steps})"
            )
        time.sleep(2)


def test_code_env_math_session(client: Client, run_id: str, created_sessions: list) -> None:
    session = client.sessions.create_session(
        agent={
            "name": f"{run_id}-agent",
            "description": "Integration test agent",
            "instructions": "You are a minimalist assistant. Reply briefly with just the requested number.",
            "environments": [{"id": "code", "kind": "code"}],
        },
        messages=[{"type": "user_message", "message": "What is 17 + 25? Reply with just the number."}],
        max_steps=8,
        max_time_s=120.0,
        idle_timeout_s=30,
    )
    created_sessions.append(session.id)

    final = _poll_until_terminal(client, session.id)
    assert str(final.status) in ("completed", "idle"), f"session ended in {final.status}; error={final.error}"
    assert (final.steps or 0) >= 1, "agent ended without taking any steps"
    assert final.error is None

    changes = client.sessions.get_session_changes(session.id)
    answer = changes.answer
    assert answer is not None, "no answer in /changes response"
    answer_str = answer if isinstance(answer, str) else json.dumps(answer, default=str)
    assert re.search(r"\b42\b", answer_str), f"agent did not return 42; full answer: {answer_str!r}"

    events_page = client.sessions.list_session_events(session.id)
    assert len(events_page.items) > 0
    event_types = {ev.type for ev in events_page.items}
    assert "AgentEvent" in event_types, f"no AgentEvent in events feed; saw: {sorted(event_types)}"

"""Browser-environment session against a search engine.

The agent is dropped on a search-engine start URL (set on the environment spec)
and asked for Paris weather without being told which engine to use. Exercises
local_browser provisioning, the agent using whatever page it lands on, and
end-to-end answer extraction.

Bing is used because headless browsers can read it without CAPTCHA. The engine
lives in the env spec, not the prompt -- mirroring how a product injects a start
URL via config.

Marked ``slow`` (~60-120s, more tokens than the code-env test). Skipped by
default; opt in with ``pytest -m "integration and slow"`` or RUN_SLOW_SDK_TESTS=1.
"""

from __future__ import annotations

import json
import os
import re
import time

import pytest

from hai_agents import Client, SessionStatus

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Engine is a test-level parameter, NOT part of the prompt. To swap engines,
# change this line and leave the prompt alone.
SEARCH_ENGINE_START_URL = "https://www.bing.com/"

TERMINAL = {"completed", "failed", "timed_out", "interrupted", "idle"}


def _poll_until_terminal(client: Client, session_id: str, timeout_s: float = 420.0) -> SessionStatus:
    start = time.time()
    while True:
        s = client.sessions.get_session_status(session_id)
        if str(s.status) in TERMINAL:
            return s
        if time.time() - start > timeout_s:
            pytest.fail(
                f"session {session_id} did not finish in {timeout_s}s "
                f"(last status: {s.status}, steps: {s.steps})"
            )
        time.sleep(3)


@pytest.mark.skipif(
    not os.environ.get("RUN_SLOW_SDK_TESTS"),
    reason="Slow browser test -- set RUN_SLOW_SDK_TESTS=1 or use -m 'integration and slow'",
)
def test_browser_session_finds_paris_weather(client: Client, run_id: str, created_sessions: list) -> None:
    session = client.sessions.create_session(
        agent={
            "name": f"{run_id}-weather",
            "description": "Integration test browser agent for weather lookup",
            "instructions": (
                "You navigate the web to answer the user's question. Use the search box on the page you "
                "land on, search for what you need, and read the result. Reply in a single concise sentence."
            ),
            "environments": [
                {
                    "id": "browser",
                    "kind": "local_browser",
                    "headless": True,
                    "width": 1280,
                    "height": 800,
                    "start_url": SEARCH_ENGINE_START_URL,
                }
            ],
        },
        messages=[
            {
                "type": "user_message",
                "message": (
                    "What is the current temperature in Paris today? "
                    "Reply with a short sentence giving the value in degrees Celsius."
                ),
            }
        ],
        max_steps=25,
        max_time_s=360.0,
        idle_timeout_s=60,
    )
    created_sessions.append(session.id)

    final = _poll_until_terminal(client, session.id)
    assert str(final.status) in ("completed", "idle"), f"session ended in {final.status}; error={final.error}"
    assert final.error is None

    changes = client.sessions.get_session_changes(session.id)
    answer = changes.answer
    assert answer is not None, "no answer in /changes response"
    answer_str = answer if isinstance(answer, str) else json.dumps(answer, default=str)

    assert re.search(r"paris", answer_str, re.IGNORECASE), f"answer doesn't mention Paris: {answer_str!r}"
    assert re.search(
        r"-?\d+(?:[.,]\d+)?\s*(?:°|degr(?:e|é|ee)s?|celsius|c\b)",
        answer_str,
        re.IGNORECASE,
    ), f"answer doesn't contain a temperature value: {answer_str!r}"

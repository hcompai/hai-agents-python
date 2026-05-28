"""Browser-environment session against a search engine.

The agent is dropped on a search-engine start URL (passed as a parameter on
the environment spec) and asked for Paris weather without being told which
search engine to use. This exercises:

  - the local_browser environment provisioning,
  - the agent's ability to use whatever page it lands on (typing into a
    search box, clicking results, extracting structured data),
  - end-to-end answer extraction.

Bing is used because headless browsers can read it without CAPTCHA, unlike
Google. The choice of engine lives in the env spec — keeping it out of the
prompt mirrors how a real product would inject the start URL via config.

Marked ``slow`` because it takes ~60-120s and consumes more tokens than the
code-env test. Skipped by default; opt in with
``pytest -m "integration and slow"`` or set ``RUN_SLOW_SDK_TESTS=1``.
"""

from __future__ import annotations

import json
import os
import re
import time

import pytest

from agent_platform import Client
from agent_platform.api.sessions import (
    get_session_changes as get_changes,
)
from agent_platform.api.sessions import (
    get_session_status as get_status,
)
from agent_platform.models.session_status import SessionStatus
from agent_platform.models.trajectory_status import TrajectoryStatus

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# Engine is a test-level parameter, NOT part of the prompt. To swap engines,
# change this line and leave the prompt alone.
SEARCH_ENGINE_START_URL = "https://www.bing.com/"

TERMINAL = {
    TrajectoryStatus.COMPLETED,
    TrajectoryStatus.FAILED,
    TrajectoryStatus.TIMED_OUT,
    TrajectoryStatus.INTERRUPTED,
    TrajectoryStatus.IDLE,
}


def _poll_until_terminal(client: Client, session_id: str, timeout_s: float = 420.0) -> SessionStatus:
    start = time.time()
    while True:
        s = get_status.sync(client=client, id=session_id)
        if s.status in TERMINAL:
            return s
        if time.time() - start > timeout_s:
            pytest.fail(
                f"session {session_id} did not finish in {timeout_s}s (last status: {s.status}, steps: {s.steps})"
            )
        time.sleep(3)


@pytest.mark.skipif(
    not os.environ.get("RUN_SLOW_SDK_TESTS"),
    reason="Slow browser test — set RUN_SLOW_SDK_TESTS=1 or use -m 'integration and slow'",
)
def test_browser_session_finds_paris_weather(client: Client, run_id: str, created_sessions: list) -> None:
    """Agent lands on the configured search engine and finds Paris weather.

    The prompt deliberately doesn't name the search engine — the agent uses
    whatever page the environment opened. This validates the "drop the agent
    on a useful starting page and let it figure out the rest" pattern.
    """
    payload = {
        "agent": {
            "name": f"{run_id}-weather",
            "description": "Integration test browser agent for weather lookup",
            "instructions": (
                "You navigate the web to answer the user's question. Use the "
                "search box on the page you land on, search for what you need, "
                "and read the result. Reply in a single concise sentence."
            ),
        },
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
        "messages": [
            {
                "type": "user_message",
                "message": (
                    "What is the current temperature in Paris today? "
                    "Reply with a short sentence giving the value in degrees Celsius."
                ),
            }
        ],
        "max_steps": 25,
        "max_time_s": 360.0,
        "idle_timeout_s": 60,
    }

    resp = client.get_httpx_client().post("/api/v2/sessions", json=payload, timeout=60.0)
    assert resp.status_code == 201, f"create failed: {resp.status_code} {resp.text[:500]}"
    session_id = resp.json()["id"]
    created_sessions.append(session_id)

    final = _poll_until_terminal(client, session_id)
    assert final.status in (TrajectoryStatus.COMPLETED, TrajectoryStatus.IDLE), (
        f"session ended in {final.status}; error={final.error}"
    )
    assert final.error is None

    ch = get_changes.sync(client=client, id=session_id).to_dict()
    answer = ch.get("answer")
    assert answer is not None, f"no answer in /changes response: {ch}"
    answer_str = answer if isinstance(answer, str) else json.dumps(answer, default=str)

    # The agent must mention Paris (loose match, case-insensitive) and report a
    # temperature: a number followed by °, C, "celsius", or "degrees".
    assert re.search(r"paris", answer_str, re.IGNORECASE), f"answer doesn't mention Paris: {answer_str!r}"
    assert re.search(
        r"-?\d+(?:[.,]\d+)?\s*(?:°|degr(?:e|é|ee)s?|celsius|c\b)",
        answer_str,
        re.IGNORECASE,
    ), f"answer doesn't contain a temperature value: {answer_str!r}"

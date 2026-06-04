"""Fixtures for live integration tests against the Agent Platform API.

These tests hit a real backend (staging by default). They are skipped when
``HAI_API_KEY_TEST`` is unset, so the suite is safe to run anywhere -- CI only
exercises them when the secret is wired up.

Never point these tests at production. The default base URL is staging, and
overriding it via ``HAI_API_BASE_URL_TEST`` is the deliberate escape hatch.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Iterator

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ImportError:
    pass

from hai_agents import Client

DEFAULT_BASE_URL = "https://agp.staging.sandboxh.ai"

# IDLE is included: a session waiting for follow-up messages is a stopping point
# for these one-shot tests, not a state to keep polling through.
TERMINAL_STATUSES = {"completed", "failed", "timed_out", "interrupted", "idle"}


def _require_key() -> str:
    key = os.environ.get("HAI_API_KEY_TEST")
    if not key:
        pytest.skip(
            "HAI_API_KEY_TEST is not set -- live integration tests skipped. "
            "Set it to a STAGING key (never prod) to run the suite."
        )
    assert key is not None
    if not key.startswith("hk-"):
        pytest.skip("HAI_API_KEY_TEST does not look like a portal-H key (hk-*).")
    return key


@pytest.fixture(scope="session")
def base_url() -> str:
    """API base URL. Defaults to staging; override with HAI_API_BASE_URL_TEST."""
    return os.environ.get("HAI_API_BASE_URL_TEST", DEFAULT_BASE_URL)


@pytest.fixture(scope="session")
def token() -> str:
    return _require_key()


@pytest.fixture
def client(token: str, base_url: str) -> Client:
    """A fresh Client per test (cheap; no connection pool reuse needed)."""
    return Client(token=token, base_url=base_url)


@pytest.fixture
def run_id() -> str:
    """Short unique id used to namespace resources created during the test."""
    return f"sdkit-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture
def created_skills(client: Client) -> Iterator[list]:
    """Track skill names created during a test and delete them on teardown."""
    names: list = []
    yield names
    for name in names:
        try:
            client.skills.delete_skill(name)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: cleanup failed for skill {name}: {exc}")


@pytest.fixture
def created_sessions(client: Client) -> Iterator[list]:
    """Track session ids and cancel any non-terminal session on teardown."""
    ids: list = []
    yield ids
    for sid in ids:
        try:
            status = client.sessions.get_session_status(sid)
            if str(status.status) not in TERMINAL_STATUSES:
                client.sessions.cancel_session(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: cleanup failed for session {sid}: {exc}")

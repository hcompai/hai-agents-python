"""Fixtures for live integration tests against the Agent Platform API.

These tests hit a real backend (staging by default). They are skipped when
``HAI_API_KEY_TEST`` is unset, so the suite is safe to run anywhere — CI only
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

# Loading the models package eagerly resolves the SDK's forward refs (mirrors
# the workaround in sdk/python/tests/conftest.py — Pydantic 2 needs every
# referenced class loaded before instantiation works).
import agent_platform.models  # noqa: F401
from agent_platform import Client

DEFAULT_BASE_URL = "https://agp.staging.sandboxh.ai"


def _require_key() -> str:
    key = os.environ.get("HAI_API_KEY_TEST")
    if not key:
        pytest.skip(
            "HAI_API_KEY_TEST is not set — live integration tests skipped. "
            "Set it to a STAGING key (never prod) to run the suite."
        )
    # pytest.skip raises, so this assert is reachable only when key is non-empty.
    # Without it, mypy doesn't narrow `key` past the skip.
    assert key is not None
    if not key.startswith("hk-"):
        pytest.skip("HAI_API_KEY_TEST does not look like a portal-H key (hk-*).")
    return key


@pytest.fixture(scope="session")
def base_url() -> str:
    """API base URL. Defaults to staging; override with HAI_API_BASE_URL_TEST."""
    return os.environ.get("HAI_API_BASE_URL_TEST", DEFAULT_BASE_URL)


@pytest.fixture(scope="session")
def api_key() -> str:
    return _require_key()


@pytest.fixture
def client(api_key: str, base_url: str) -> Client:
    """A fresh Client per test (cheap; no connection pool reuse needed)."""
    return Client(api_key=api_key, base_url=base_url)


@pytest.fixture
def run_id() -> str:
    """Short unique id used to namespace resources created during the test.

    Combines a timestamp + 6 hex chars so concurrent runs don't collide and
    leaked resources (cleanup failed, test crashed) can be identified after
    the fact by their prefix.
    """
    return f"sdkit-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture
def created_skills(client: Client) -> Iterator[list]:
    """Track skill ids created during a test and delete them on teardown.

    Tests append the returned Skill (or its id) to this list; the fixture
    will call DELETE on each, ignoring 404s. Cleanup failures log a warning
    but never fail the test — a leaked skill in staging is not a test bug.
    """
    from agent_platform.api.skills import (
        delete_skill as delete_skill,
    )

    ids: list = []
    yield ids
    for sid in ids:
        try:
            delete_skill.sync_detailed(client=client, id=sid)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: cleanup failed for skill {sid}: {exc}")


@pytest.fixture
def created_sessions(client: Client) -> Iterator[list]:
    """Track session ids and cancel any non-terminal session on teardown.

    Sessions can't be hard-deleted; the best we can do is cancel running ones
    so they stop consuming quota. Terminal sessions stay in history.
    """
    from agent_platform.api.sessions import (
        cancel_session as cancel_session,
    )
    from agent_platform.api.sessions import (
        get_session_status as get_status,
    )
    from agent_platform.models.trajectory_status import TrajectoryStatus

    TERMINAL = {
        TrajectoryStatus.COMPLETED,
        TrajectoryStatus.FAILED,
        TrajectoryStatus.TIMED_OUT,
        TrajectoryStatus.INTERRUPTED,
        TrajectoryStatus.IDLE,
    }

    ids: list = []
    yield ids
    for sid in ids:
        try:
            s = get_status.sync(client=client, id=sid)
            if s and s.status not in TERMINAL:
                cancel_session.sync_detailed(client=client, id=sid)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: cleanup failed for session {sid}: {exc}")

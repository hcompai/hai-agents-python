"""Shared fixtures and helpers for SDK model round-trip tests.

For each model, construct a canonical input dict matching the API schema, parse it
through the SDK model's from_dict() (the public parsing entrypoint), serialize back
via to_dict(), and assert the result equals the input. from_dict()/to_dict() is the
SDK's actual public round-trip contract and handles the UNSET sentinel and
discriminated-union resolution that model_validate() bypasses.

Datetime fields are the most common mismatch source: Pydantic v2 emits ISO 8601 with
a `+00:00` offset, and python-dateutil's isoparse (used in from_dict()) re-emits the
same form via .isoformat(). assert_json_equal() still normalizes to guard against
future format drift.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from hai_agents.models.agent import Agent
from hai_agents.models.agent_record import AgentRecord
from hai_agents.models.session import Session
from hai_agents.models.session_request import SessionRequest
from hai_agents.models.session_status import SessionStatus
from hai_agents.models.session_summary import SessionSummary
from hai_agents.models.skill_record import SkillRecord
from hai_agents.models.trajectory_status import TrajectoryStatus
from hai_agents.models.user_message_event import UserMessageEvent


def _normalize_datetimes(obj: Any) -> Any:
    """Recursively replace ``Z`` suffix with ``+00:00`` for byte-equal comparison.

    Pydantic v2 / python-dateutil .isoformat() produces: '2024-01-01T00:00:00+00:00'
    Some OpenAPI tools / human-written fixtures use:       '2024-01-01T00:00:00Z'

    Both are valid ISO 8601 representations.  We canonicalize to ``+00:00`` (the
    form produced by Python's datetime.isoformat()) before comparing, so tests
    pass whether the fixture was written with ``Z`` or ``+00:00``.
    """
    if isinstance(obj, str) and obj.endswith("Z") and "T" in obj:
        return obj[:-1] + "+00:00"
    if isinstance(obj, dict):
        return {k: _normalize_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_datetimes(v) for v in obj]
    return obj


def assert_json_equal(actual: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert two dicts are equal after datetime normalization.

    Use this instead of plain ``==`` to allow the ``Z`` vs ``+00:00`` difference
    between a fixture written with ``Z`` for readability and Pydantic's canonical
    output (``+00:00``).
    """
    actual_norm = _normalize_datetimes(actual)
    expected_norm = _normalize_datetimes(expected)
    assert actual_norm == expected_norm, (
        f"\nActual:   {json.dumps(actual_norm, sort_keys=True, indent=2)}"
        f"\nExpected: {json.dumps(expected_norm, sort_keys=True, indent=2)}"
    )


# ---------------------------------------------------------------------------
# Canonical payload fixtures
#
# Each fixture matches the backend public_api/ model shape field-for-field.
# Rules:
#   - Omit fields whose canonical value is None or UNSET — from_dict() keeps
#     them as UNSET defaults; to_dict() omits UNSET fields; so input == output.
#   - For fields that ARE non-null (required or with concrete defaults), include them.
#   - Field names must be exactly the JSON keys the API uses (snake_case per schema).
# ---------------------------------------------------------------------------


@pytest.fixture
def session_request_payload() -> Dict[str, Any]:
    """Canonical SessionRequest dict matching SDK SessionRequest model.

    ``agent`` carries its own environments (a string catalog id passes through
    without any union-resolution attempt — the simplest valid agent variant).
    """
    return {
        "agent": "test-agent",
    }


@pytest.fixture
def session_payload(session_request_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical Session dict — full envelope (id + request + status + timestamps).

    ``status.steps`` defaults to 0 (not UNSET), so to_dict() always emits it —
    the fixture must include it for round-trip equality.
    """
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "request": session_request_payload,
        "status": {"status": "running", "steps": 0},
        "created_at": "2024-01-01T00:00:00+00:00",
        # started_at / finished_at omitted — UNSET default
    }


@pytest.fixture
def skill_record_payload() -> Dict[str, Any]:
    """Canonical SkillRecord dict matching backend public_api/skill.py:SkillRecord.

    Fields: id, name, description, body, source (None|str), url_pattern (None|str),
            uri (None|str), reserved (bool), created_at, updated_at.

    Note: source/url_pattern/uri are nullable (None), NOT UNSET — SkillRecord.to_dict()
    includes them even when None (they are not UNSET-guarded in the template).
    The fixture must include them as None so input == output. ``reserved`` is a
    required bool (default False on the backend) and must be present here too,
    otherwise from_dict()/model_validate() raise.
    """
    return {
        "id": "00000000-0000-0000-0000-000000000003",
        "name": "test-skill",
        "description": "A test skill for roundtrip validation.",
        "body": "## Instructions\nDo something useful.",
        "source": None,
        "url_pattern": None,
        "uri": None,
        "reserved": False,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-06-01T12:00:00+00:00",
    }


@pytest.fixture
def agent_payload() -> Dict[str, Any]:
    """Canonical Agent spec dict.

    Required: name, description, environments. Other fields are UNSET by
    default and excluded by to_dict() when absent.
    """
    return {
        "name": "test-agent",
        "description": "A test agent for roundtrip validation.",
        "environments": [],
    }


@pytest.fixture
def agent_record_payload(agent_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical AgentRecord dict — catalog row (id + spec + reserved + timestamps)."""
    return {
        "id": "00000000-0000-0000-0000-000000000002",
        "spec": agent_payload,
        "reserved": False,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-06-01T12:00:00+00:00",
    }

"""SDK Pydantic v2 models round-trip JSON byte-identically.

Each test parses a canonical payload through the model's from_dict() (the SDK's
public parsing entrypoint) and asserts to_dict() reproduces the input (after the
documented ISO 8601 datetime normalization). from_dict()/to_dict() is the actual
public round-trip contract — it exercises the same path users call, including the
UNSET sentinel and discriminated-union resolution that model_validate() bypasses.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict

from hai_agents.models.agent import Agent
from hai_agents.models.agent_record import AgentRecord
from hai_agents.models.session import Session
from hai_agents.models.session_request import SessionRequest
from hai_agents.models.skill_record import SkillRecord

from .conftest import assert_json_equal


def _roundtrip(model_cls: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse payload via from_dict() then serialize via to_dict().

    This exercises the SDK's canonical public round-trip path:
      - from_dict(): parses raw JSON-dict into typed model (handles UNSET
        sentinels, UUID coercion, isoparse for datetimes, discriminated unions)
      - to_dict(): serializes back to plain dict (handles UNSET exclusion,
        UUID → str, datetime → .isoformat())

    Fixtures must omit UNSET-defaulted optional fields (they won't appear in
    to_dict() output, causing input != output).  Fixtures must include None-valued
    nullable fields (they DO appear in to_dict() output for non-UNSET-guarded
    fields like Skill.source).
    """
    instance = model_cls.from_dict(payload)
    return instance.to_dict()


# ---------------------------------------------------------------------------
# Session-related roundtrip
# ---------------------------------------------------------------------------


def test_session_request_roundtrip(session_request_payload: Dict[str, Any]) -> None:
    """SessionRequest round-trips: agent+environments parse and re-serialize identically.

    Tests the core session creation payload — the most critical user-facing model.
    When agent is a string catalog id, it passes through from_dict() as a string
    and to_dict() returns it unchanged.
    """
    serialized = _roundtrip(SessionRequest, session_request_payload)
    assert_json_equal(serialized, session_request_payload)


def test_session_full_roundtrip(session_payload: Dict[str, Any]) -> None:
    """Session (full envelope: id + request + status + timestamps) round-trips."""
    serialized = _roundtrip(Session, session_payload)
    assert_json_equal(serialized, session_payload)


# ---------------------------------------------------------------------------
# Skill roundtrip
# ---------------------------------------------------------------------------


def test_skill_record_roundtrip(skill_record_payload: Dict[str, Any]) -> None:
    """SkillRecord round-trips all 9 fields including nullable source/url_pattern/uri.

    Unlike UNSET-guarded fields, SkillRecord's nullable string fields (source,
    url_pattern, uri) ARE included in to_dict() even when None — so the
    fixture must supply them as None to achieve input == output.
    """
    serialized = _roundtrip(SkillRecord, skill_record_payload)
    assert_json_equal(serialized, skill_record_payload)


# ---------------------------------------------------------------------------
# Agent roundtrip
# ---------------------------------------------------------------------------


def test_agent_roundtrip(agent_payload: Dict[str, Any]) -> None:
    """Agent spec round-trips: name + description (required fields only).

    Optional fields (model, instructions, subagents, skills, memory_namespace)
    default to UNSET and are excluded by to_dict() — fixture omits them.
    """
    serialized = _roundtrip(Agent, agent_payload)
    assert_json_equal(serialized, agent_payload)


def test_agent_record_roundtrip(agent_record_payload: Dict[str, Any]) -> None:
    """AgentRecord (catalog row: id + spec + reserved + timestamps) round-trips."""
    serialized = _roundtrip(AgentRecord, agent_record_payload)
    assert_json_equal(serialized, agent_record_payload)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_no_attrs_in_generated_models() -> None:
    """Structural enforcement: no ``attrs`` imports in models/.

    Models must be Pydantic v2 only; ``attrs`` and ``dataclass`` are forbidden,
    so this test fails loudly if they reappear.

    Note: client.py and types.py deliberately use attrs (for AuthenticatedClient
    and File/Response) — that is expected and out of scope here.  Only models/.
    """
    import hai_agents.models as models_pkg

    models_dir = Path(models_pkg.__file__).parent
    forbidden_patterns = [
        "from attrs",
        "_attrs_define",
        "@_attrs_define",
        "from dataclasses",
        "@dataclass",
    ]

    violations: list[str] = []
    for py_file in models_dir.glob("*.py"):
        text = py_file.read_text()
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{py_file.name}: contains forbidden pattern '{pattern}'")

    assert not violations, "Models must not use attrs/dataclass:\n" + "\n".join(violations)


def test_datetime_field_serializes_as_iso8601(skill_record_payload: Dict[str, Any]) -> None:
    """Datetime fields must serialize as ISO 8601 strings.

    SkillRecord carries two required datetime fields (created_at, updated_at). We verify:
      1. The serialized value is a string (not a datetime object)
      2. It contains 'T' (ISO 8601 separator)
      3. It has a timezone offset ('Z' or '+00:00') — both are valid per ISO 8601

    The round-trip uses isoparse (dateutil) for parsing + .isoformat() for
    serialization — both sides produce '+00:00' form for UTC, so no 'Z' ambiguity.
    """
    instance = SkillRecord.from_dict(skill_record_payload)
    serialized = instance.to_dict()

    for field_name in ("created_at", "updated_at"):
        value = serialized[field_name]
        assert isinstance(value, str), f"{field_name} not serialized as string: {type(value)}"
        assert "T" in value, f"{field_name} not ISO 8601: {value!r}"
        assert value.endswith(("Z", "+00:00")), f"{field_name} missing UTC timezone: {value!r}"


def test_model_validate_simple_fields(skill_record_payload: Dict[str, Any]) -> None:
    """Verify model_validate() works for models without complex union/UNSET fields.

    SkillRecord has no UNSET-guarded fields (its optional strings are nullable,
    not UNSET) and no discriminated unions, so model_validate() works identically
    to from_dict() for it.

    For models with UNSET sentinel defaults or discriminated unions (SessionRequest,
    Agent), from_dict() is the correct parsing path.
    """
    via_validate = SkillRecord.model_validate(skill_record_payload)
    assert isinstance(via_validate.created_at, datetime.datetime)
    assert str(via_validate.id) == skill_record_payload["id"]

    via_from_dict = SkillRecord.from_dict(skill_record_payload)
    assert via_validate.id == via_from_dict.id
    assert via_validate.name == via_from_dict.name
    assert via_validate.created_at == via_from_dict.created_at

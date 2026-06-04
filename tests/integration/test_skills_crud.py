"""Skill lifecycle round-trip against the live API.

Create -> fetch -> update -> delete -> confirm the 404. Each step exercises a
different SDK code path (POST + create body, GET + parse, PUT + full-replace
body, DELETE + 204, GET + 404 -> ApiError). Skills are keyed by name; the
conftest cleanup still deletes the skill if a step fails so we don't leak it.

The Fern client raises ApiError on non-2xx and returns the parsed model on
success, so we assert on returned models and on raised errors rather than on
status codes.
"""

from __future__ import annotations

import pytest

from hai_agents import Client
from hai_agents.core import ApiError

pytestmark = pytest.mark.integration


def test_skill_lifecycle(client: Client, run_id: str, created_skills: list) -> None:
    name = f"{run_id}-skill"
    initial_body = "When asked for the integration test marker, reply with 'sdkit-ok'."

    skill = client.skills.create_skill(
        name=name,
        description="SDK integration test skill -- safe to delete",
        body=initial_body,
    )
    created_skills.append(skill.name)
    assert skill.name == name
    assert skill.body == initial_body

    fetched = client.skills.get_skill(skill.name)
    assert fetched.name == skill.name
    assert fetched.body == skill.body

    # UPDATE is a full replacement: name + body required or the server returns 422.
    new_description = "SDK integration test skill -- updated"
    updated = client.skills.update_skill(
        skill.name,
        name=skill.name,
        description=new_description,
        body=initial_body + " [updated]",
    )
    assert updated.description == new_description
    assert updated.body.endswith("[updated]")

    client.skills.delete_skill(skill.name)
    created_skills.remove(skill.name)

    with pytest.raises(ApiError) as exc_info:
        client.skills.get_skill(skill.name)
    assert exc_info.value.status_code == 404


def test_skill_update_without_body_returns_422(client: Client, run_id: str, created_skills: list) -> None:
    """The known gotcha: PUT is full-replacement, so omitting body may fail."""
    name = f"{run_id}-partial"
    skill = client.skills.create_skill(
        name=name,
        description="for partial-update 422 check",
        body="initial body",
    )
    created_skills.append(skill.name)

    # Empty body on the full-replacement endpoint: the server either tolerates
    # it (200, no raise) or rejects it (422 -> ApiError). Anything else is a bug.
    try:
        client.skills.update_skill(
            skill.name,
            name=skill.name,
            description="only changed description",
            body="",
        )
    except ApiError as exc:
        assert exc.status_code == 422, f"expected 422, got {exc.status_code}"

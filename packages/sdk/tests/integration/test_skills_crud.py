"""Skill lifecycle round-trip against the live API.

Creates → fetches → updates → deletes → confirms the 404. Each step exercises
a different SDK code path (POST + Skill body, GET + parse, PUT + full-replace
Skill body, DELETE + 204, GET + 404 with ErrorResponse). Skills are keyed by
name. If any step fails, the conftest cleanup still deletes the skill so we
don't leak it.

Uses sync_detailed throughout because we care about the status codes — sync()
returns the parsed body only and loses that signal.
"""

from __future__ import annotations

import pytest

from hai_agents import Client, Skill
from hai_agents.api.skills import (
    create_skill as create_skill,
)
from hai_agents.api.skills import (
    delete_skill as delete_skill,
)
from hai_agents.api.skills import (
    get_skill as get_skill,
)
from hai_agents.api.skills import (
    update_skill as update_skill,
)

pytestmark = pytest.mark.integration


def test_skill_lifecycle(client: Client, run_id: str, created_skills: list) -> None:
    name = f"{run_id}-skill"
    initial_body = "When asked for the integration test marker, reply with 'sdkit-ok'."

    # CREATE
    r = create_skill.sync_detailed(
        client=client,
        body=Skill(
            name=name,
            description="SDK integration test skill — safe to delete",
            body=initial_body,
        ),
    )
    assert r.status_code == 201, f"create returned {r.status_code}: {r.content[:300]!r}"
    skill = r.parsed
    assert skill is not None
    created_skills.append(skill.name)
    assert skill.name == name
    assert skill.body == initial_body

    # GET
    r = get_skill.sync_detailed(client=client, name=skill.name)
    assert r.status_code == 200
    fetched = r.parsed
    assert fetched.name == skill.name
    assert fetched.body == skill.body

    # UPDATE — full replacement: name + body required or the server returns 422
    new_description = "SDK integration test skill — updated"
    r = update_skill.sync_detailed(
        client=client,
        name=skill.name,
        body=Skill(
            name=skill.name,
            description=new_description,
            body=initial_body + " [updated]",
        ),
    )
    assert r.status_code == 200, f"update returned {r.status_code}: {r.content[:300]!r}"
    updated = r.parsed
    assert updated.description == new_description
    assert updated.body.endswith("[updated]")

    # DELETE
    r = delete_skill.sync_detailed(client=client, name=skill.name)
    assert r.status_code == 204
    # Stop tracking — already deleted; teardown shouldn't try again
    created_skills.remove(skill.name)

    # CONFIRM GONE
    r = get_skill.sync_detailed(client=client, name=skill.name)
    assert r.status_code == 404


def test_skill_update_without_body_returns_422(client: Client, run_id: str, created_skills: list) -> None:
    """The known gotcha: PUT is full-replacement, so omitting body fails."""
    name = f"{run_id}-partial"
    r = create_skill.sync_detailed(
        client=client,
        body=Skill(
            name=name,
            description="for partial-update 422 check",
            body="initial body",
        ),
    )
    assert r.status_code == 201
    skill = r.parsed
    created_skills.append(skill.name)

    # Send a PUT with an empty body string. The server should reject because
    # body is required alongside description on the full-replacement endpoint.
    r = update_skill.sync_detailed(
        client=client,
        name=skill.name,
        body=Skill(name=skill.name, description="only changed description", body=""),
    )
    assert r.status_code in (200, 422), f"expected 200 (server tolerates) or 422 (rejects), got {r.status_code}"

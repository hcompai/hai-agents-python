"""A release bumps every version stamp together and refuses specs that prod or the pinned runtime cannot serve."""

import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
bump_version = runpy.run_path(str(ROOT / "scripts" / "bump_version.py"))
check_release = runpy.run_path(str(ROOT / "scripts" / "check_release.py"))


def _copy_stamped_files(root: Path) -> None:
    for relative in bump_version["STAMPS"]:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, root / relative)


def test_bump_moves_every_stamp_to_the_next_patch(tmp_path):
    _copy_stamped_files(tmp_path)
    major, minor, patch = bump_version["current"](tmp_path).split(".")

    new = bump_version["bump"](tmp_path)

    assert new == f"{major}.{minor}.{int(patch) + 1}"
    for relative, patterns in bump_version["STAMPS"].items():
        text = (tmp_path / relative).read_text()
        assert all([stamp for _, stamp, _ in pattern.findall(text)] == [new] for pattern in patterns), relative


def test_bump_writes_nothing_when_a_stamp_is_out_of_step(tmp_path):
    _copy_stamped_files(tmp_path)
    wrapper = tmp_path / "src/hai_agents/core/client_wrapper.py"
    wrapper.write_text(wrapper.read_text().replace('"X-HCompany-Client-Version": "', '"X-HCompany-Client-Version": "9'))
    before = {relative: (tmp_path / relative).read_text() for relative in bump_version["STAMPS"]}

    with pytest.raises(SystemExit):
        bump_version["bump"](tmp_path)

    assert {relative: (tmp_path / relative).read_text() for relative in bump_version["STAMPS"]} == before


def _spec(paths: dict, schemas: dict | None = None) -> dict:
    return {"paths": paths, "components": {"schemas": schemas or {}}}


def _post(schema: dict) -> dict:
    return {"post": {"requestBody": {"content": {"application/json": {"schema": schema}}}}}


def test_operations_prod_does_not_serve_block_the_release():
    sdk = _spec({"/api/v2/agents": {"get": {}}, "/api/v2/agents/{name}/restore": {"post": {}}})
    prod = _spec({"/api/v2/agents": {"get": {}}})

    assert check_release["missing_operations"](sdk, prod) == ["POST /api/v2/agents/{name}/restore"]


def test_session_fields_the_runtime_does_not_accept_block_the_release():
    environment = {"properties": {"kind": {"type": "string"}, "settle_s": {"type": "number"}}}
    agent = {
        "properties": {
            "environments": {
                "type": "array",
                "items": {"oneOf": [{"type": "string"}, {"$ref": "#/components/schemas/Env"}]},
            },
            "subagents": {"type": "array", "items": {"$ref": "#/components/schemas/Agent"}},
        }
    }
    session = {"properties": {"agent": {"anyOf": [{"type": "string"}, {"$ref": "#/components/schemas/Agent"}]}}}
    sdk = _spec(
        {"/api/v2/sessions": _post(session), "/api/v2/environments": _post({"$ref": "#/components/schemas/Env"})},
        {"Agent": agent, "Env": environment},
    )
    old_environment = {"properties": {"kind": {"type": "string"}}}
    runtime = _spec(
        {"/api/v2/sessions": _post(session), "/api/v2/environments": _post({"$ref": "#/components/schemas/Env"})},
        {"Agent": agent, "Env": old_environment},
    )

    assert check_release["unaccepted_session_fields"](sdk, runtime) == [
        "POST /api/v2/sessions: agent.environments[].settle_s",
    ]

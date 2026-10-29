"""The OpenAPI spec's const+default discriminators must survive into the generated models.

The API discriminates several tagged unions on a constant field (the environment ``kind``,
``OnePasswordConfig.provider``, event ``type`` tags). The spec declares those fields with both
``const`` and ``default``, but the Fern generator drops the default and emits ``= None``: the
serializer then omits the field entirely and the server rejects the payload with a 422
("Unable to extract tag using discriminator 'kind'") because union discrimination runs before
per-variant defaults are applied.

A model that the spec only ever references as a tagged-union member loses the field altogether;
Fern carries the tag on the union's variant classes (``Environment_Web``) instead.

These tests pin the hand-restored defaults so a future regeneration that clobbers them fails CI
loudly instead of shipping another field-omission 422.
"""

import json
import pathlib
import typing
from collections import defaultdict

import pytest

import hai_agents.types as types_module
from hai_agents.core.http_client import get_request_body
from hai_agents.types import Environment_Android, Environment_Desktop, Environment_Web

SPEC = json.loads((pathlib.Path(__file__).parent.parent / "openapi.json").read_text())

MINIMAL_KWARGS: dict[str, dict[str, typing.Any]] = {
    "OnePasswordConfig": {"op_vault_id": "vault_1"},
    "ToolResultEvent": {"tool_req": {"tool_name": "click"}, "result": "ok"},
    "UserMessageEvent": {"message": "hi"},
    "ErrorEvent": {"error": "boom", "origin": "loop"},
    "ToolResultBatch": {"results": []},
    "CronTiming": {"expression": "0 9 * * *", "timezone": "Europe/Paris"},
    "Workstation": {"id": "workstation"},
}


def _spec_const_defaults() -> list[tuple[str, str, typing.Any]]:
    cases = []
    for schema_name, schema in SPEC["components"]["schemas"].items():
        for prop_name, prop in schema.get("properties", {}).items():
            if isinstance(prop, dict) and "const" in prop and "default" in prop:
                cases.append((schema_name, prop_name, prop["default"]))
    return cases


def _union_only_tags() -> set[tuple[str, str]]:
    """(schema, tag) pairs for schemas the spec references only as members of a tagged union."""
    tags: defaultdict[str, set[str]] = defaultdict(set)
    standalone: set[str] = set()

    def walk(node: typing.Any, tag: str | None = None) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        if not isinstance(node, dict):
            return
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if tag:
                tags[name].add(tag)
            else:
                standalone.add(name)
        discriminator = node.get("discriminator")
        for key, value in node.items():
            if key in ("oneOf", "anyOf") and isinstance(discriminator, dict):
                for member in value:
                    walk(member, discriminator["propertyName"])
            elif key != "discriminator":
                walk(value)

    walk(SPEC)
    return {(name, tag) for name, names_tags in tags.items() if name not in standalone for tag in names_tags}


def test_spec_declares_the_known_discriminator_defaults():
    """Guard the guard: if the spec stops declaring these, the drift test below would go vacuous."""
    found = {(s, p) for s, p, _ in _spec_const_defaults()}
    assert {("Browser", "kind"), ("OnePasswordConfig", "provider")} <= found


@pytest.mark.parametrize("schema_name,prop_name,expected_default", _spec_const_defaults())
def test_generated_model_sends_spec_default(schema_name, prop_name, expected_default):
    model = getattr(types_module, schema_name)
    if prop_name not in model.model_fields:
        assert (schema_name, prop_name) in _union_only_tags(), (
            f"{schema_name}.{prop_name} is missing from the generated model, but the spec also sends "
            f"{schema_name} outside a tagged union, so those payloads would omit the tag."
        )
        return
    instance = model(**MINIMAL_KWARGS.get(schema_name, {}))
    assert getattr(instance, prop_name) == expected_default, (
        f"{schema_name}.{prop_name} should default to {expected_default!r} per the OpenAPI spec; "
        "a regeneration probably clobbered the hand-restored default (see this file's docstring)."
    )
    json_body, _ = get_request_body(json=instance, data=None, request_options=None, omit=None)
    assert json_body[prop_name] == expected_default, "an attribute default that exclude-unset drops is no fix"


@pytest.mark.parametrize(
    "instance,field,expected",
    [
        (Environment_Web(id="browser", start_url="https://x.test"), "kind", "web"),
        (Environment_Desktop(id="box", host="user_device"), "kind", "desktop"),
        (Environment_Android(id="phone"), "kind", "android"),
    ],
)
def test_union_variant_sends_its_tag(instance, field, expected):
    json_body, _ = get_request_body(json=instance, data=None, request_options=None, omit=None)
    assert json_body[field] == expected

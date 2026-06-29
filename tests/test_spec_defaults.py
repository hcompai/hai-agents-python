"""The OpenAPI spec's const+default discriminators must survive into the generated models.

The API discriminates several tagged unions on a constant field (``Browser.kind``,
``OnePasswordConfig.provider``, event ``type`` tags). The spec declares those fields with both
``const`` and ``default``, but the Fern generator drops the default and emits ``= None`` — the
serializer then omits the field entirely and the server rejects the payload with a 422
("Unable to extract tag using discriminator 'kind'") because union discrimination runs before
per-variant defaults are applied.

These tests pin the hand-restored defaults so a future regeneration that clobbers them fails CI
loudly instead of shipping another field-omission 422.
"""

import json
import pathlib
import typing

import pytest

import hai_agents.types as types_module
from hai_agents.core.http_client import get_request_body
from hai_agents.types import Browser, OnePasswordConfig, ToolResultEvent, UserMessageEvent

OPENAPI_PATH = pathlib.Path(__file__).parent.parent / "openapi.json"

FIELD_DROPPED_ENTIRELY = {
    ("UserMessageBatch", "type"),
    ("AnswerEvent", "kind"),
    ("FlowEvent", "kind"),
    ("MessageEvent", "kind"),
    ("ObservationEvent", "kind"),
    ("PolicyEvent", "kind"),
    ("BrowserVisualMode", "type"),
    ("BrowserTextMode", "type"),
}

MINIMAL_KWARGS: dict[str, dict[str, typing.Any]] = {
    "Browser": {"id": "browser"},
    "OnePasswordConfig": {"op_vault_id": "vault_1"},
    "ToolResultEvent": {"tool_req": {"tool_name": "click"}, "result": "ok"},
    "UserMessageEvent": {"message": "hi"},
    "ErrorEvent": {"error": "boom", "origin": "loop"},
    "ToolResultBatch": {"results": []},
}


def _spec_const_defaults() -> list[tuple[str, str, typing.Any]]:
    spec = json.loads(OPENAPI_PATH.read_text())
    cases = []
    for schema_name, schema in spec["components"]["schemas"].items():
        for prop_name, prop in schema.get("properties", {}).items():
            if isinstance(prop, dict) and "const" in prop and "default" in prop:
                cases.append((schema_name, prop_name, prop["default"]))
    return cases


def test_spec_declares_the_known_discriminator_defaults():
    """Guard the guard: if the spec stops declaring these, the drift test below would go vacuous."""
    found = {(s, p) for s, p, _ in _spec_const_defaults()}
    assert {("Browser", "kind"), ("OnePasswordConfig", "provider")} <= found


def test_dropped_fields_are_actually_absent():
    """A regeneration that restores a skipped field must force it back under test, not stay skipped."""
    for schema_name, prop_name in FIELD_DROPPED_ENTIRELY:
        model = getattr(types_module, schema_name)
        assert prop_name not in model.model_fields, (
            f"{schema_name}.{prop_name} is back on the generated model; drop it from "
            "FIELD_DROPPED_ENTIRELY and add MINIMAL_KWARGS so its default is verified."
        )


@pytest.mark.parametrize("schema_name,prop_name,expected_default", _spec_const_defaults())
def test_generated_model_honors_spec_default(schema_name, prop_name, expected_default):
    if (schema_name, prop_name) in FIELD_DROPPED_ENTIRELY:
        pytest.skip("field dropped from the generated model; tag carried by the request-body wrappers")
    model = getattr(types_module, schema_name)
    instance = model(**MINIMAL_KWARGS.get(schema_name, {}))
    assert getattr(instance, prop_name) == expected_default, (
        f"{schema_name}.{prop_name} should default to {expected_default!r} per the OpenAPI spec; "
        "a regeneration probably clobbered the hand-restored default (see this file's docstring)."
    )


@pytest.mark.parametrize(
    "instance,field,expected",
    [
        (Browser(id="browser", start_url="https://x.test"), "kind", "web"),
        (OnePasswordConfig(op_vault_id="vault_1"), "provider", "onepassword"),
        (ToolResultEvent(tool_req={"tool_name": "click"}, result="ok"), "kind", "tool_result"),
        (UserMessageEvent(message="hi"), "type", "user_message"),
    ],
)
def test_default_reaches_the_wire_body(instance, field, expected):
    """The default must actually serialize — an attribute default that exclude-unset drops is no fix."""
    json_body, _ = get_request_body(json=instance, data=None, request_options=None, omit=None)
    assert json_body[field] == expected

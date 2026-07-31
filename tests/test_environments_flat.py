"""Flat keyword arguments on the union-bodied environment endpoints still reach the wire.

``create_environment``/``update_environment`` take a ``kind``-discriminated union body, which
Fern can only express as a single ``request=`` model. These tests pin the hand-written flat-kwargs
layer that keeps the documented call style working, and assert against the serialized request body
rather than the model — an ergonomic wrapper that drops or mangles a field is no fix.
"""

from __future__ import annotations

import json
import typing

import httpx
import pytest

from hai_agents import AsyncClient, Client
from hai_agents.environments import (
    CreateEnvironmentRequest_Desktop,
    CreateEnvironmentRequest_Web,
    UpdateEnvironmentRequestBody_Web,
)

ENVIRONMENT_RESPONSE = {"id": "wide-browser", "kind": "web"}


class _Recorder:
    """Captures the single request a call makes, and replays a canned environment."""

    def __init__(self) -> None:
        self.request: typing.Optional[httpx.Request] = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        return httpx.Response(200, json=ENVIRONMENT_RESPONSE)

    @property
    def body(self) -> typing.Dict[str, typing.Any]:
        assert self.request is not None, "no request was sent"
        return json.loads(self.request.content)

    @property
    def path(self) -> str:
        assert self.request is not None, "no request was sent"
        return self.request.url.path


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def client(recorder: _Recorder) -> Client:
    return Client(
        api_key="hk-test",
        base_url="http://api.test",
        httpx_client=httpx.Client(transport=httpx.MockTransport(recorder)),
    )


@pytest.fixture
def async_client(recorder: _Recorder) -> AsyncClient:
    return AsyncClient(
        api_key="hk-test",
        base_url="http://api.test",
        httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
    )


def test_create_accepts_flat_fields(client: Client, recorder: _Recorder) -> None:
    """The call style the docs use, and everything written against <=1.0.5."""
    client.environments.create_environment(
        id="wide-browser",
        start_url="https://www.google.com",
        mode={"type": "visual", "width": 1920, "height": 1080},
    )
    assert recorder.body == {
        "kind": "web",
        "id": "wide-browser",
        "start_url": "https://www.google.com",
        "mode": {"type": "visual", "width": 1920, "height": 1080},
    }


def test_create_defaults_to_web_but_accepts_an_explicit_kind(client: Client, recorder: _Recorder) -> None:
    client.environments.create_environment(id="wide-browser", kind="web", vault_id="vault_1")
    assert recorder.body["kind"] == "web"


def test_create_routes_desktop_fields_to_the_desktop_member(client: Client, recorder: _Recorder) -> None:
    client.environments.create_environment(id="my-box", kind="desktop", host="user_device")
    assert recorder.body == {"kind": "desktop", "id": "my-box", "host": "user_device"}


def test_create_still_accepts_a_prebuilt_request(client: Client, recorder: _Recorder) -> None:
    """The generated 1.0.6+ style must keep working — this is additive, not a swap."""
    client.environments.create_environment(
        request=CreateEnvironmentRequest_Web(id="wide-browser", vault_id="vault_1"),
    )
    assert recorder.body == {"kind": "web", "id": "wide-browser", "vault_id": "vault_1"}


def test_create_accepts_a_prebuilt_desktop_request(client: Client, recorder: _Recorder) -> None:
    client.environments.create_environment(
        request=CreateEnvironmentRequest_Desktop(id="my-box", host="user_device"),
    )
    assert recorder.body["kind"] == "desktop"


@pytest.mark.parametrize(
    "spec",
    [
        {"id": "wide-browser", "start_url": "https://x.test", "headless": True},
        {"id": "wide-browser", "mode": {"type": "text", "markdown": True}},
        {"id": "wide-browser", "network": {"proxy_url": "http://user:pass@proxy.test:8080"}},
        {"id": "my-box", "kind": "desktop", "host": "user_device"},
    ],
)
def test_flat_fields_and_prebuilt_request_send_the_same_body(spec: typing.Dict[str, typing.Any]) -> None:
    """This layer is ergonomics only: neither style may produce a body the other cannot."""
    bodies = []
    for call_style in ("flat", "request"):
        recorder = _Recorder()
        client = Client(
            api_key="hk-test",
            base_url="http://api.test",
            httpx_client=httpx.Client(transport=httpx.MockTransport(recorder)),
        )
        if call_style == "flat":
            client.environments.create_environment(**spec)
        else:
            member = CreateEnvironmentRequest_Desktop if spec.get("kind") == "desktop" else CreateEnvironmentRequest_Web
            client.environments.create_environment(request=member(**spec))
        bodies.append(recorder.body)
    assert bodies[0] == bodies[1]


def test_update_derives_the_path_from_the_spec_id(client: Client, recorder: _Recorder) -> None:
    client.environments.update_environment(id="wide-browser", start_url="https://example.com")
    assert recorder.path == "/api/v2/environments/wide-browser"
    assert recorder.body == {
        "kind": "web",
        "id": "wide-browser",
        "start_url": "https://example.com",
    }


def test_update_accepts_the_path_positionally_alongside_the_spec_id(client: Client, recorder: _Recorder) -> None:
    """The <=1.0.5 signature was ``update_environment(id_, *, id, ...)``; both ids still land."""
    client.environments.update_environment("wide-browser", id="wide-browser", headless=True)
    assert recorder.path == "/api/v2/environments/wide-browser"
    assert recorder.body["id"] == "wide-browser"
    assert recorder.body["headless"] is True


def test_update_path_and_spec_id_may_differ(client: Client, recorder: _Recorder) -> None:
    client.environments.update_environment("old-id", id="new-id")
    assert recorder.path == "/api/v2/environments/old-id"
    assert recorder.body["id"] == "new-id"


def test_update_still_accepts_a_prebuilt_request_keyed_by_id(client: Client, recorder: _Recorder) -> None:
    """``id=`` here is the path segment, as in the generated client — not a stray flat field."""
    client.environments.update_environment(
        id="wide-browser",
        request=UpdateEnvironmentRequestBody_Web(id="wide-browser", start_url="https://example.com"),
    )
    assert recorder.path == "/api/v2/environments/wide-browser"
    assert recorder.body["start_url"] == "https://example.com"


def test_unknown_field_fails_fast_instead_of_riding_along_as_an_extra(client: Client) -> None:
    """Union members are ``extra="allow"``, so without this guard a typo becomes a server 422."""
    with pytest.raises(TypeError, match="start_ur1"):
        client.environments.create_environment(id="wide-browser", start_ur1="https://x.test")


def test_browser_field_on_a_desktop_environment_is_rejected(client: Client) -> None:
    with pytest.raises(TypeError, match="start_url"):
        client.environments.create_environment(id="my-box", kind="desktop", host="user_device", start_url="https://x")


def test_mixing_request_and_flat_fields_is_rejected(client: Client) -> None:
    with pytest.raises(TypeError, match="not both"):
        client.environments.create_environment(
            request=CreateEnvironmentRequest_Web(id="wide-browser"),
            start_url="https://x.test",
        )


def test_missing_id_is_reported_as_a_missing_argument(client: Client) -> None:
    with pytest.raises(TypeError, match="'id'"):
        client.environments.create_environment(start_url="https://x.test")


def test_unmodelled_kind_points_at_the_request_escape_hatch(client: Client) -> None:
    with pytest.raises(TypeError, match="request="):
        client.environments.create_environment(id="x", kind="quantum")


async def test_async_create_accepts_flat_fields(async_client: AsyncClient, recorder: _Recorder) -> None:
    await async_client.environments.create_environment(id="wide-browser", vault_id="vault_1")
    assert recorder.body == {"kind": "web", "id": "wide-browser", "vault_id": "vault_1"}


async def test_async_update_derives_the_path_from_the_spec_id(async_client: AsyncClient, recorder: _Recorder) -> None:
    await async_client.environments.update_environment(id="wide-browser", start_url="https://example.com")
    assert recorder.path == "/api/v2/environments/wide-browser"
    assert recorder.body["start_url"] == "https://example.com"


async def test_async_mixing_request_and_flat_fields_is_rejected(async_client: AsyncClient) -> None:
    with pytest.raises(TypeError, match="not both"):
        await async_client.environments.create_environment(
            request=CreateEnvironmentRequest_Web(id="wide-browser"),
            start_url="https://x.test",
        )

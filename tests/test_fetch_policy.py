from __future__ import annotations

import httpx
import pytest

from hai_agents.core.api_error import ApiError
from hai_agents.core.http_client import HttpClient


def client_returning(*statuses: int) -> tuple[HttpClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(queue.pop(0) if len(queue) > 1 else queue[0], json={})

    client = HttpClient(
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_timeout=lambda: 5,
        base_headers=lambda: {},
        base_url=lambda: "https://api.test",
        base_max_retries=2,
    )
    return client, seen


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("hai_agents.core.http_client.time.sleep", lambda _s: None)


def test_5xx_is_retried_only_for_idempotent_methods():
    client, seen = client_returning(503, 200)
    assert client.request(path="sessions", method="GET").status_code == 200
    assert len(seen) == 2

    client, seen = client_returning(503, 200)
    assert client.request(path="sessions", method="POST").status_code == 503
    assert len(seen) == 1


def test_429_is_retried_for_any_method():
    client, seen = client_returning(429, 200)
    assert client.request(path="sessions", method="POST").status_code == 200
    assert len(seen) == 2


def test_409_is_never_retried():
    client, seen = client_returning(409, 200)
    assert client.request(path="sessions", method="GET").status_code == 409
    assert len(seen) == 1


def dropping_client() -> tuple[HttpClient, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        if len(seen) == 1:
            raise httpx.RemoteProtocolError("server disconnected")
        return httpx.Response(200, json={})

    client = HttpClient(
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_timeout=lambda: 5,
        base_headers=lambda: {},
        base_url=lambda: "https://api.test",
    )
    return client, seen


def test_connection_drop_is_resent_only_for_idempotent_methods():
    client, seen = dropping_client()
    with pytest.raises(httpx.RemoteProtocolError):
        client.request(path="sessions", method="POST")
    assert seen == ["POST"]

    client, seen = dropping_client()
    assert client.request(path="sessions", method="GET").status_code == 200
    assert seen == ["GET", "GET"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"detail": "Quota exceeded"}, "Quota exceeded (status_code: 429)"),
        ({"message": "Not found"}, "Not found (status_code: 429)"),
        ({"detail": {"message": "nested"}}, "nested (status_code: 429)"),
        ({"detail": [{"msg": "a"}, {"msg": "b"}]}, "a; b (status_code: 429)"),
    ],
)
def test_api_error_leads_with_server_detail(body, expected):
    assert str(ApiError(status_code=429, body=body)) == expected


def test_api_error_without_detail_keeps_full_dump():
    err = ApiError(status_code=502, headers={"x": "y"}, body="<html>bad gateway</html>")
    assert str(err) == "headers: {'x': 'y'}, status_code: 502, body: <html>bad gateway</html>"

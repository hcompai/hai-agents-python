from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from hai_agents_local.holotab.commands import MAX_BODY_BYTES, LocalCommandServer

WAIT_S = 10.0


@pytest.fixture
def server() -> Iterator[LocalCommandServer]:
    running = LocalCommandServer()
    running.start()
    yield running
    running.stop()


def get(server: LocalCommandServer, path: str, token: str | None = None) -> Any:
    request = urllib.request.Request(
        f"{server.base_url}{path}", headers={"Authorization": f"Bearer {token or server.token}"}
    )
    return urllib.request.urlopen(request, timeout=5)


def test_a_command_goes_out_and_its_result_comes_back(server: LocalCommandServer) -> None:
    answer: list[Any] = []
    worker = threading.Thread(target=lambda: answer.append(server.submit("current_url", {}, WAIT_S)))
    worker.start()
    with get(server, f"/api/v1/commands/{server.session_id}/commands?wait_for_seconds=5") as page:
        [command] = json.loads(page.read())
    assert command["name"] == "current_url"
    assert server.deliver(command["id"], {"result": "https://example.com"})
    worker.join(WAIT_S)
    assert answer == ["https://example.com"]


def test_nothing_queued_answers_no_content_rather_than_an_empty_list(server: LocalCommandServer) -> None:
    with get(server, f"/api/v1/commands/{server.session_id}/commands?wait_for_seconds=0") as page:
        assert page.status == 204


def test_the_token_is_required(server: LocalCommandServer) -> None:
    with pytest.raises(urllib.error.HTTPError) as refused:
        get(server, f"/api/v1/commands/{server.session_id}/commands", token="wrong")
    assert refused.value.code == 401


def test_an_unknown_path_is_not_found(server: LocalCommandServer) -> None:
    with pytest.raises(urllib.error.HTTPError) as refused:
        get(server, "/api/v1/other")
    assert refused.value.code == 404


def test_a_result_over_the_cap_is_refused_before_it_is_read(server: LocalCommandServer) -> None:
    request = urllib.request.Request(
        f"{server.base_url}/api/v1/commands/c1/result",
        data=b"{}",
        headers={"Authorization": f"Bearer {server.token}", "Content-Length": str(MAX_BODY_BYTES + 1)},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)
    assert refused.value.code == 413


def test_another_session_is_told_nothing(server: LocalCommandServer) -> None:
    assert server.take("not-this-session", 0) == []


def test_it_listens_only_on_loopback(server: LocalCommandServer) -> None:
    assert server.base_url.startswith("http://127.0.0.1:")


def test_a_page_error_is_raised_never_returned(server: LocalCommandServer) -> None:
    outcome: list[str] = []

    def ask() -> None:
        try:
            server.submit("get_tabs", {}, WAIT_S)
        except RuntimeError as error:
            outcome.append(str(error))

    worker = threading.Thread(target=ask)
    worker.start()
    [command] = server.take(server.session_id, 5)
    server.deliver(command["id"], {"error": "get_tabs is not supported"})
    worker.join(WAIT_S)
    assert outcome == ["get_tabs is not supported"]


def test_a_silent_extension_times_out_and_says_so(server: LocalCommandServer) -> None:
    with pytest.raises(RuntimeError, match="did not answer"):
        server.submit("current_url", {}, timeout_s=0.05)


def test_a_stopped_server_releases_a_command_still_waiting(server: LocalCommandServer) -> None:
    outcome: list[str] = []

    def ask() -> None:
        try:
            server.submit("goto", {"url": "https://example.com"}, timeout_s=WAIT_S)
        except RuntimeError as error:
            outcome.append(str(error))

    worker = threading.Thread(target=ask)
    worker.start()
    server.take(server.session_id, 5)
    server.stop()
    worker.join(WAIT_S)
    assert outcome == ["the local command server stopped before Chrome answered goto"]


def test_a_command_submitted_after_the_server_stopped_fails_at_once(server: LocalCommandServer) -> None:
    server.stop()
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="not running"):
        server.submit("goto", {"url": "https://example.com"}, timeout_s=WAIT_S)
    assert time.monotonic() - started < 1.0
    assert not server._queue and not server._waiters


def test_arguments_that_cannot_travel_as_json_fail_before_they_are_queued(server: LocalCommandServer) -> None:
    with pytest.raises(TypeError, match="cannot be sent to Chrome"):
        server.submit("goto", {"url": object()}, timeout_s=WAIT_S)
    assert not server._queue


def test_commands_a_poll_could_not_deliver_go_to_the_next_poll(
    server: LocalCommandServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert server._server is not None
    handler = server._server.RequestHandlerClass
    send, drops = handler._send, [ConnectionResetError("the poll went away")]

    def flaky(self: Any, status: int, body: Any) -> None:
        if status == 200 and drops:
            raise drops.pop()
        send(self, status, body)

    monkeypatch.setattr(handler, "_send", flaky)
    answer: list[Any] = []
    worker = threading.Thread(target=lambda: answer.append(server.submit("current_url", {}, WAIT_S)))
    worker.start()
    deadline = time.monotonic() + WAIT_S
    while not server._queue and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(OSError):
        get(server, f"/api/v1/commands/{server.session_id}/commands?wait_for_seconds=5")
    with get(server, f"/api/v1/commands/{server.session_id}/commands?wait_for_seconds=5") as page:
        [command] = json.loads(page.read())
    assert command["name"] == "current_url"
    server.deliver(command["id"], {"result": "https://example.com"})
    worker.join(WAIT_S)
    assert answer == ["https://example.com"]


def test_a_command_that_times_out_is_never_run_later(server: LocalCommandServer) -> None:
    with pytest.raises(RuntimeError, match="did not answer"):
        server.submit("goto", {"url": "https://example.com"}, timeout_s=0.05)
    assert server.take(server.session_id, 0) == []


def test_a_stopped_waiter_leaves_nothing_queued(server: LocalCommandServer) -> None:
    worker = threading.Thread(target=lambda: pytest.raises(RuntimeError, server.submit, "goto", {}, WAIT_S))
    worker.start()
    deadline = time.monotonic() + WAIT_S
    while not server._queue and time.monotonic() < deadline:
        time.sleep(0.01)
    server.stop()
    worker.join(WAIT_S)
    assert not server._queue


def test_the_late_result_of_an_abandoned_command_is_dropped(server: LocalCommandServer) -> None:
    worker = threading.Thread(target=lambda: pytest.raises(RuntimeError, server.submit, "goto", {}, 0.3))
    worker.start()
    [command] = server.take(server.session_id, 5)
    worker.join(WAIT_S)
    assert server.deliver(command["id"], {"result": "late"}) is False
    assert server._results == {}

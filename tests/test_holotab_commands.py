from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from hai_agents_local.holotab import commands
from hai_agents_local.holotab.commands import (
    DEFAULT_COMMAND_TIMEOUT_S,
    MAX_BODY_BYTES,
    SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S,
    LocalCommandServer,
)

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


def poll(server: LocalCommandServer, results: list, wait: int = 5) -> threading.Thread:
    def run() -> None:
        with get(server, f"/api/v1/commands/{server.session_id}/commands?wait_for_seconds={wait}") as page:
            results.append((page.status, page.read()))

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def wait_for(check: Any) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


def test_a_newer_poll_supersedes_an_older_one_so_a_dropped_poll_never_takes_a_command(
    server: LocalCommandServer,
) -> None:
    older: list = []
    first = poll(server, older)
    assert wait_for(lambda: server._polls == 1)
    newer: list = []
    second = poll(server, newer)
    first.join(WAIT_S)
    assert older == [(204, b"")]
    answer: list[Any] = []
    worker = threading.Thread(target=lambda: answer.append(server.submit("current_url", {}, WAIT_S)))
    worker.start()
    second.join(WAIT_S)
    [command] = json.loads(newer[0][1])
    server.deliver(command["id"], {"result": "https://example.com"})
    worker.join(WAIT_S)
    assert answer == ["https://example.com"]


def test_a_poll_whose_client_already_left_is_seen_as_gone() -> None:
    left, right = socket.socketpair()
    try:
        assert commands._left(right) is False
        left.sendall(b"GET / HTTP/1.1\r\n")
        assert commands._left(right) is False
        left.close()
        right.recv(64)
        assert commands._left(right) is True
    finally:
        right.close()


def raw(server: LocalCommandServer, request: bytes) -> bytes:
    host, port = server._server.server_address[:2]
    with socket.create_connection((host, port), timeout=5) as conn:
        conn.sendall(request)
        chunks = []
        while chunk := conn.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def test_a_negative_length_is_refused_and_the_connection_closed(server: LocalCommandServer) -> None:
    reply = raw(
        server,
        f"POST /api/v1/commands/x/result HTTP/1.1\r\nAuthorization: Bearer {server.token}\r\n"
        "Content-Length: -1\r\n\r\n".encode(),
    )
    assert reply.startswith(b"HTTP/1.1 400")
    assert b"Connection: close" in reply


@pytest.mark.parametrize("authorization", ["Bearer wrong", "Bearer caf\u00e9"])
def test_a_refused_request_closes_its_connection_so_its_body_is_never_read_as_a_request(
    server: LocalCommandServer, authorization: str
) -> None:
    body = b"GET /api/v1/commands/x/commands HTTP/1.1\r\n\r\n"
    reply = raw(
        server,
        f"POST /api/v1/commands/x/result HTTP/1.1\r\nAuthorization: {authorization}\r\n".encode("latin-1")
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body,
    )
    assert reply.startswith(b"HTTP/1.1 401")
    assert reply.count(b"HTTP/1.1") == 1


def test_a_client_that_resets_its_connection_prints_nothing(
    server: LocalCommandServer, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        raise ConnectionResetError("the poll went away")
    except ConnectionResetError:
        server._server.handle_error(None, ("127.0.0.1", 1))
    assert capsys.readouterr().err == ""
    try:
        raise ValueError("a real bug")
    except ValueError:
        server._server.handle_error(None, ("127.0.0.1", 1))
    assert "a real bug" in capsys.readouterr().err


def test_a_failed_server_ends_the_waiting_command_and_every_later_one_at_once(server: LocalCommandServer) -> None:
    failures: list[str] = []

    def submit() -> None:
        try:
            server.submit("goto", {}, WAIT_S)
        except RuntimeError as exc:
            failures.append(str(exc))

    worker = threading.Thread(target=submit)
    worker.start()
    assert wait_for(lambda: server._queue)
    started = time.monotonic()
    server.fail("Chrome stopped serving this session (closed)")
    worker.join(WAIT_S)
    with pytest.raises(RuntimeError, match=r"Chrome stopped serving this session \(closed\)"):
        server.submit("goto", {}, WAIT_S)
    assert failures == ["Chrome stopped serving this session (closed)"]
    assert time.monotonic() - started < 1
    assert server.take(server.session_id, 0) == []


def test_a_command_gives_up_before_the_agent_does() -> None:
    assert SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S == 60.0
    assert DEFAULT_COMMAND_TIMEOUT_S < SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S

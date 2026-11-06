from __future__ import annotations

import json
import socket
import stat
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from hai_agents_local.holotab.endpoint import STORE_EXTENSION_ID, TcpEndpoint, UnixEndpoint, own_uid, peer_uid
from hai_agents_local.holotab.link import HoloTabLink, base_url_error

from .holotab_helpers import WAIT_S, hello, short_dir, tcp_link, unix_link

UNIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="a Unix socket endpoint does not exist on Windows")


@pytest.fixture(params=["unix", "tcp"])
def link(request: pytest.FixtureRequest) -> Iterator[HoloTabLink]:
    if request.param == "unix" and sys.platform == "win32":
        pytest.skip("a Unix socket endpoint does not exist on Windows")
    with short_dir() as folder:
        running = unix_link(folder) if request.param == "unix" else tcp_link(folder)
        running.start()
        yield running
        running.close()


def test_a_worker_that_reconnects_is_waited_for_and_still_offered_meanwhile() -> None:
    with short_dir() as folder:
        link = unix_link(folder)
        assert link.seen_within(120) is False
        assert link.wait_connected(0.01) is False

        link._conn, link.extension = socket.socket(), {"id": STORE_EXTENSION_ID, "version": "1.4.11"}
        assert link.connected
        link._conn.close()
        link._conn = None
        link._seen_at = 1.0
        assert link.seen_within(1e12) is True

        def comes_back() -> None:
            link._conn = socket.socket()
            link._handle({"type": "HELLO", "extension": STORE_EXTENSION_ID, "version": "1.4.11"})

        threading.Thread(target=comes_back).start()
        assert link.wait_connected(WAIT_S)


def test_the_link_waits_for_chrome_without_polling_and_stops_at_once(link: HoloTabLink) -> None:
    accepting = [t for t in threading.enumerate() if t.name == "holotab-link"]
    assert link._server is not None
    assert link._server.gettimeout() is None
    link.close()
    for thread in accepting:
        thread.join(WAIT_S)
        assert not thread.is_alive()


@UNIX_ONLY
def test_the_socket_is_the_users_alone_and_goes_when_the_link_closes() -> None:
    with short_dir() as folder:
        link = unix_link(folder)
        link.start()
        path = folder / "l.sock"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        link.close()
        assert not path.exists()


def test_the_token_file_is_the_users_alone_and_goes_when_the_link_closes() -> None:
    with short_dir() as folder:
        link = tcp_link(folder)
        link.start()
        info = folder / "link.json"
        assert stat.S_IMODE(info.stat().st_mode) == 0o600 or sys.platform == "win32"
        assert json.loads(info.read_text())["token"]
        link.close()
        assert not info.exists()


def test_an_endpoint_another_process_serves_is_never_replaced(link: HoloTabLink) -> None:
    second = HoloTabLink(
        link.endpoint.__class__(
            link.endpoint.path if isinstance(link.endpoint, UnixEndpoint) else link.endpoint.info_path
        )
    )
    with pytest.raises(RuntimeError, match="already served"):
        second.start()
    second.close()
    assert link.connected is False
    link.endpoint.connect().close()


@UNIX_ONLY
def test_a_path_that_is_not_a_socket_is_never_replaced() -> None:
    with short_dir() as folder:
        path = folder / "l.sock"
        path.write_text("mine")
        with pytest.raises(RuntimeError, match="unsafe"):
            HoloTabLink(UnixEndpoint(path)).start()
        assert path.read_text() == "mine"


@UNIX_ONLY
def test_a_dead_socket_file_is_replaced() -> None:
    with short_dir() as folder:
        path = folder / "l.sock"
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(path))
        stale.close()
        link = HoloTabLink(UnixEndpoint(path))
        link.start()
        try:
            assert link._server is not None
        finally:
            link.close()


def test_a_dead_token_file_is_replaced() -> None:
    with short_dir() as folder:
        (folder / "link.json").write_text(json.dumps({"port": 9, "token": "old"}))
        link = tcp_link(folder)
        link.start()
        try:
            assert json.loads((folder / "link.json").read_text())["token"] != "old"
        finally:
            link.close()


def test_a_hello_makes_the_extension_known(link: HoloTabLink) -> None:
    conn = hello(link, "1.4.11")
    assert link.extension == {"id": STORE_EXTENSION_ID, "version": "1.4.11"}
    assert link.seen_within(WAIT_S)
    conn.close()


def test_a_connection_that_does_not_begin_with_hello_is_dropped(link: HoloTabLink) -> None:
    conn = link.endpoint.open()
    conn.sendall(b'{"type": "SERVING", "channel": "x"}\n')
    assert conn.recv(1) == b""
    assert not link.connected
    assert link.serving == {}


def test_a_tcp_connection_without_the_token_is_dropped() -> None:
    with short_dir() as folder:
        link = tcp_link(folder)
        link.start()
        try:
            conn = link.endpoint.connect()
            conn.sendall(b'{"type": "AUTH", "token": "wrong"}\n{"type": "HELLO", "extension": "x"}\n')
            assert conn.recv(1) == b""
            assert not link.connected
        finally:
            link.close()


def test_a_channel_is_served_when_the_extension_acknowledges_it(link: HoloTabLink) -> None:
    conn = hello(link)
    reader = conn.makefile("rb")
    answers: list[dict | None] = []
    worker = threading.Thread(
        target=lambda: answers.append(
            link.serve("run-1", "http://127.0.0.1:9", "token", label="Chat", client="Agents API")
        )
    )
    worker.start()
    asked = json.loads(reader.readline())
    assert asked == {
        "type": "SERVE_CHANNEL",
        "channel": "run-1",
        "base_url": "http://127.0.0.1:9",
        "api_key": "token",
        "start_url": None,
        "label": "Chat",
        "client": "Agents API",
    }
    conn.sendall(json.dumps({"type": "SERVING", "channel": "run-1"}).encode() + b"\n")
    worker.join(WAIT_S)
    assert answers == [{"type": "SERVING", "channel": "run-1"}]

    link.stop("run-1")
    assert json.loads(reader.readline()) == {"type": "STOP_CHANNEL", "channel": "run-1"}
    link.relabel("run-1", "New title")
    assert json.loads(reader.readline())["title"] == "New title"
    conn.close()


def test_a_stopped_channel_is_no_longer_served(link: HoloTabLink) -> None:
    link._handle({"type": "SERVING", "channel": "run-1"})
    assert "run-1" in link.serving
    link._handle({"type": "STOPPED", "channel": "run-1"})
    assert link.serving == {}


def test_an_error_from_the_extension_ends_the_wait_with_nothing_served(link: HoloTabLink) -> None:
    conn = hello(link)
    reader = conn.makefile("rb")
    answers: list[dict | None] = []
    worker = threading.Thread(target=lambda: answers.append(link.serve("run-1", "http://127.0.0.1:9", "token")))
    worker.start()
    reader.readline()
    conn.sendall(json.dumps({"type": "ERROR", "channel": "run-1", "error": "no tab"}).encode() + b"\n")
    worker.join(WAIT_S)
    assert answers == [None]
    assert link.last_error == "no tab"
    conn.close()


def serve_in_thread(link: HoloTabLink, channel: str, answers: dict[str, dict | None]) -> threading.Thread:
    worker = threading.Thread(
        target=lambda: answers.__setitem__(channel, link.serve(channel, "http://127.0.0.1:9", "token"))
    )
    worker.start()
    return worker


def send(conn: socket.socket, message: dict) -> None:
    conn.sendall(json.dumps(message).encode() + b"\n")


def test_an_error_for_one_channel_leaves_the_other_pending_serves_waiting(link: HoloTabLink) -> None:
    conn = hello(link)
    reader = conn.makefile("rb")
    answers: dict[str, dict | None] = {}
    first = serve_in_thread(link, "run-1", answers)
    reader.readline()
    second = serve_in_thread(link, "run-2", answers)
    reader.readline()

    send(conn, {"type": "ERROR", "channel": "run-2", "error": "no tab"})
    second.join(WAIT_S)
    assert answers == {"run-2": None}
    assert first.is_alive()

    send(conn, {"type": "SERVING", "channel": "run-1"})
    first.join(WAIT_S)
    assert answers["run-1"] == {"type": "SERVING", "channel": "run-1"}
    conn.close()


def test_an_error_that_names_only_its_request_fails_the_oldest_pending_serve(link: HoloTabLink) -> None:
    conn = hello(link)
    reader = conn.makefile("rb")
    answers: dict[str, dict | None] = {}
    first = serve_in_thread(link, "run-1", answers)
    reader.readline()
    second = serve_in_thread(link, "run-2", answers)
    reader.readline()

    send(conn, {"type": "ERROR", "for": "SERVE_CHANNEL", "error": "no tab"})
    first.join(WAIT_S)
    assert answers == {"run-1": None}
    assert second.is_alive()

    send(conn, {"type": "SERVING", "channel": "run-2"})
    second.join(WAIT_S)
    assert answers["run-2"] == {"type": "SERVING", "channel": "run-2"}
    conn.close()


def test_an_error_that_names_its_channel_beats_the_oldest_pending_serve(link: HoloTabLink) -> None:
    conn = hello(link)
    reader = conn.makefile("rb")
    answers: dict[str, dict | None] = {}
    first = serve_in_thread(link, "run-1", answers)
    reader.readline()
    second = serve_in_thread(link, "run-2", answers)
    reader.readline()

    send(conn, {"type": "ERROR", "for": "SERVE_CHANNEL", "channel": "run-2", "error": "no tab"})
    second.join(WAIT_S)
    assert answers == {"run-2": None}
    assert first.is_alive()

    send(conn, {"type": "SERVING", "channel": "run-1"})
    first.join(WAIT_S)
    assert answers["run-1"] == {"type": "SERVING", "channel": "run-1"}
    conn.close()


def test_a_serving_that_arrives_after_the_serve_timed_out_is_stopped(link: HoloTabLink) -> None:
    conn = hello(link)
    reader = conn.makefile("rb")
    assert link.serve("run-1", "http://127.0.0.1:9", "token", timeout_s=0.05) is None
    assert link.last_error == "HoloTab did not acknowledge the Chrome channel within 0.05s"
    assert json.loads(reader.readline())["type"] == "SERVE_CHANNEL"

    send(conn, {"type": "SERVING", "channel": "run-1"})
    assert json.loads(reader.readline()) == {"type": "STOP_CHANNEL", "channel": "run-1"}
    assert "run-1" not in link.serving
    conn.close()


def test_a_retry_after_a_timed_out_serve_is_served_by_the_next_serving(link: HoloTabLink) -> None:
    conn = hello(link)
    reader = conn.makefile("rb")
    assert link.serve("run-1", "http://127.0.0.1:9", "token", timeout_s=0.05) is None
    reader.readline()
    answers: dict[str, dict | None] = {}
    retry = serve_in_thread(link, "run-1", answers)
    reader.readline()

    send(conn, {"type": "SERVING", "channel": "run-1"})
    retry.join(WAIT_S)
    assert answers["run-1"] == {"type": "SERVING", "channel": "run-1"}
    conn.close()


def test_a_second_hello_is_refused_while_the_first_connection_holds_the_link(link: HoloTabLink) -> None:
    first = hello(link, "1.4.10")
    first.settimeout(WAIT_S)
    first_reader = first.makefile("rb")
    link._handle({"type": "SERVING", "channel": "run-1"})

    second = link.endpoint.open()
    second.settimeout(WAIT_S)
    second.sendall(json.dumps({"type": "HELLO", "extension": STORE_EXTENSION_ID, "version": "1.4.11"}).encode() + b"\n")
    assert second.makefile("rb").readline() == b""

    assert link.extension == {"id": STORE_EXTENSION_ID, "version": "1.4.10"}
    assert "run-1" in link.serving
    link.stop("run-1")
    assert json.loads(first_reader.readline()) == {"type": "STOP_CHANNEL", "channel": "run-1"}
    second.close()
    first.close()


def test_the_link_is_free_for_a_new_hello_once_the_live_connection_ends(link: HoloTabLink) -> None:
    first = hello(link, "1.4.10")
    link._handle({"type": "SERVING", "channel": "run-1"})
    first.close()
    deadline = time.monotonic() + WAIT_S
    while link.connected and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not link.connected and link.serving == {}

    second = hello(link, "1.4.11")
    assert link.extension == {"id": STORE_EXTENSION_ID, "version": "1.4.11"}
    second.close()


def test_closing_the_link_ends_a_wait_for_chrome_at_once(link: HoloTabLink) -> None:
    waited: list[bool] = []
    waiter = threading.Thread(target=lambda: waited.append(link.wait_connected(60)))
    waiter.start()
    time.sleep(0.05)
    started = time.monotonic()
    link.close()
    waiter.join(WAIT_S)
    assert waited == [False] and time.monotonic() - started < WAIT_S


def test_closing_the_link_hangs_up_on_the_extension_while_its_reader_is_open(link: HoloTabLink) -> None:
    conn = hello(link)
    conn.settimeout(WAIT_S)
    reader = conn.makefile("rb")
    link.close()
    assert reader.readline() == b""


def test_serving_without_the_extension_answers_none_and_says_why(link: HoloTabLink) -> None:
    assert link.serve("run-1", "http://127.0.0.1:9", "token") is None
    assert link.last_error is not None


@pytest.mark.parametrize(
    ("channel", "base_url", "key"),
    [
        ("", "http://127.0.0.1:1", "k"),
        ("a\nb", "http://127.0.0.1:1", "k"),
        ("a", "http://example.com", "k"),
        ("a", "http://127.0.0.1:1", ""),
    ],
)
def test_a_channel_the_extension_must_not_be_given_is_refused(
    link: HoloTabLink, channel: str, base_url: str, key: str
) -> None:
    with pytest.raises(ValueError):
        link.serve(channel, base_url, key)


@pytest.mark.parametrize(
    ("url", "refused"),
    [
        ("https://agp.example.ai", False),
        ("http://127.0.0.1:8080", False),
        ("http://localhost:1", False),
        ("http://example.com", True),
        ("https://user:pw@example.com", True),
        ("https://example.com/?a=1", True),
    ],
)
def test_the_base_url_must_be_https_or_loopback(url: str, refused: bool) -> None:
    assert (base_url_error(url) is not None) is refused


@pytest.mark.skipif(not sys.platform.startswith(("darwin", "linux")), reason="peer credentials need macOS or Linux")
def test_the_peer_of_a_socket_is_known_by_its_user_id() -> None:
    left, right = socket.socketpair()
    try:
        assert peer_uid(left) == own_uid()
    finally:
        left.close()
        right.close()


def test_the_tcp_endpoint_listens_on_loopback_only() -> None:
    with short_dir() as folder:
        endpoint = TcpEndpoint(folder / "link.json")
        server = endpoint.bind()
        try:
            assert server.getsockname()[0] == "127.0.0.1"
        finally:
            server.close()
            endpoint.release(server)

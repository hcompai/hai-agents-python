from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hai_agents_local.holotab.endpoint import TcpEndpoint, UnixEndpoint

UNIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets")


@pytest.fixture
def socket_path() -> Iterator[Path]:
    if sys.platform == "win32":
        pytest.skip("Unix sockets")
    with tempfile.TemporaryDirectory(prefix="hai-ep-", dir="/tmp") as folder:
        yield Path(folder) / "link.sock"


@UNIX_ONLY
def test_losing_the_bind_race_leaves_the_live_socket_alone(socket_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    winner = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    real_bind = socket.socket.bind

    def racing_bind(self: socket.socket, address: Any) -> None:
        if self is not winner:
            winner.bind(address)
            winner.listen(8)
        real_bind(self, address)

    monkeypatch.setattr(socket.socket, "bind", racing_bind)
    try:
        with pytest.raises(RuntimeError, match="already linked to another program"):
            UnixEndpoint(socket_path).bind()
        monkeypatch.undo()
        assert socket_path.exists()
        UnixEndpoint(socket_path).connect().close()
    finally:
        winner.close()


@UNIX_ONLY
def test_a_socket_nothing_answers_on_is_replaced(socket_path: Path) -> None:
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()
    endpoint = UnixEndpoint(socket_path)
    server = endpoint.bind()
    try:
        endpoint.connect().close()
    finally:
        server.close()
        endpoint.release()


def test_a_token_file_that_cannot_be_deleted_still_frees_the_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = TcpEndpoint(tmp_path / "link.json"), TcpEndpoint(tmp_path / "link.json")
    server = first.bind()

    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("the file is open in another process")

    monkeypatch.setattr(Path, "unlink", refuse)
    server.close()
    first.release()
    monkeypatch.undo()

    replacement = second.bind()
    replacement.close()
    second.release()


def accept_one(endpoint: TcpEndpoint, server: socket.socket) -> dict[str, Any]:
    outcome: dict[str, Any] = {}

    def run() -> None:
        conn, _ = server.accept()
        outcome["conn"] = conn
        outcome["admitted"] = endpoint.admits(conn)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    outcome["thread"] = thread
    return outcome


def test_a_tcp_client_and_its_link_prove_the_token_to_each_other_and_then_talk(tmp_path: Path) -> None:
    link = TcpEndpoint(tmp_path / "link.json")
    server = link.bind()
    try:
        outcome = accept_one(link, server)
        client = TcpEndpoint(tmp_path / "link.json").open()
        outcome["thread"].join(5)
        assert outcome["admitted"] is True
        client.sendall(b"after the handshake\n")
        assert outcome["conn"].recv(64) == b"after the handshake\n"
        assert client.gettimeout() is None and outcome["conn"].gettimeout() is None
        client.close()
        outcome["conn"].close()
    finally:
        server.close()
        link.release()


def test_a_process_on_the_port_of_a_crashed_link_never_sees_the_token_and_is_refused(tmp_path: Path) -> None:
    squatter = socket.create_server(("127.0.0.1", 0))
    info = tmp_path / "link.json"
    info.write_text(json.dumps({"port": squatter.getsockname()[1], "token": "the-users-token"}))
    heard: list[bytes] = []

    def answer_without_the_token() -> None:
        conn, _ = squatter.accept()
        with conn:
            heard.append(conn.recv(4096))
            conn.sendall(json.dumps({"type": "AUTH", "nonce": "n", "proof": "guess"}).encode() + b"\n")
            heard.append(conn.recv(4096))

    thread = threading.Thread(target=answer_without_the_token, daemon=True)
    thread.start()
    try:
        with pytest.raises(ConnectionRefusedError, match="not this user's HoloTab link"):
            TcpEndpoint(info).open()
        thread.join(5)
    finally:
        squatter.close()
    assert b"the-users-token" not in b"".join(heard)
    assert heard[-1] == b""


@pytest.mark.parametrize("answer", [b"HTTP/1.1 400 Bad Request\r\n", b"[1, 2]\n"])
def test_a_listener_that_does_not_answer_a_json_object_is_refused_so_the_shim_retries(
    tmp_path: Path, answer: bytes
) -> None:
    squatter = socket.create_server(("127.0.0.1", 0))
    info = tmp_path / "link.json"
    info.write_text(json.dumps({"port": squatter.getsockname()[1], "token": "the-users-token"}))

    def answer_in_plain_text() -> None:
        conn, _ = squatter.accept()
        with conn:
            conn.recv(4096)
            conn.sendall(answer)

    thread = threading.Thread(target=answer_in_plain_text, daemon=True)
    thread.start()
    try:
        with pytest.raises(ConnectionRefusedError, match="JSON object"):
            TcpEndpoint(info).open()
        thread.join(5)
    finally:
        squatter.close()


def test_a_client_that_cannot_prove_the_token_is_refused(tmp_path: Path) -> None:
    link = TcpEndpoint(tmp_path / "link.json")
    server = link.bind()
    try:
        outcome = accept_one(link, server)
        info = json.loads((tmp_path / "link.json").read_text())
        (tmp_path / "other.json").write_text(json.dumps({**info, "token": "a-wrong-token"}))
        with pytest.raises(OSError):
            TcpEndpoint(tmp_path / "other.json").open().recv(1)
        outcome["thread"].join(5)
        assert outcome["admitted"] is False
    finally:
        server.close()
        link.release()


@pytest.mark.parametrize("sent", [b"", b"x" * 4096])
def test_a_connection_that_never_authenticates_is_dropped_in_bounded_time_and_memory(
    tmp_path: Path, sent: bytes
) -> None:
    link = TcpEndpoint(tmp_path / "link.json")
    link.auth_timeout_s = 0.3
    server = link.bind()
    try:
        outcome = accept_one(link, server)
        raw = socket.create_connection(server.getsockname()[:2])
        raw.sendall(sent)
        started = time.monotonic()
        outcome["thread"].join(5)
        assert outcome["admitted"] is False
        assert time.monotonic() - started < 2
        raw.close()
    finally:
        server.close()
        link.release()

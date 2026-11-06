from __future__ import annotations

import socket
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hai_agents_local.holotab.endpoint import TcpEndpoint, UnixEndpoint

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets")


@pytest.fixture
def socket_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="hai-ep-", dir="/tmp") as folder:
        yield Path(folder) / "link.sock"


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
        with pytest.raises(RuntimeError, match="already served"):
            UnixEndpoint(socket_path).bind()
        monkeypatch.undo()
        assert socket_path.exists()
        UnixEndpoint(socket_path).connect().close()
    finally:
        winner.close()


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
        endpoint.release(server)


def test_a_token_file_that_cannot_be_deleted_still_frees_the_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = TcpEndpoint(tmp_path / "link.json"), TcpEndpoint(tmp_path / "link.json")
    server = first.bind()

    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("the file is open in another process")

    monkeypatch.setattr(Path, "unlink", refuse)
    server.close()
    first.release(server)
    monkeypatch.undo()

    replacement = second.bind()
    replacement.close()
    second.release(replacement)

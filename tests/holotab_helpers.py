from __future__ import annotations

import json
import socket
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hai_agents_local.holotab.endpoint import STORE_EXTENSION_ID, TcpEndpoint, UnixEndpoint
from hai_agents_local.holotab.link import HoloTabLink

WAIT_S = 5.0
HELLO = {"type": "HELLO", "extension": STORE_EXTENSION_ID, "version": "1.4.11", "protocol": 1}


@contextmanager
def short_dir() -> Iterator[Path]:
    """A short path: a Unix socket's takes at most 104 bytes on a Mac."""
    with tempfile.TemporaryDirectory(dir="/tmp") as folder:
        yield Path(folder)


def hello(link: HoloTabLink, version: str = "1.4.11") -> socket.socket:
    """Connects the way the shim does and says HELLO as the extension."""
    conn = link.endpoint.open()
    conn.sendall(json.dumps({**HELLO, "version": version}).encode() + b"\n")
    assert link.wait_connected(WAIT_S)
    return conn


def unix_link(folder: Path) -> HoloTabLink:
    return HoloTabLink(UnixEndpoint(folder / "l.sock"))


def tcp_link(folder: Path) -> HoloTabLink:
    return HoloTabLink(TcpEndpoint(folder / "link.json"))

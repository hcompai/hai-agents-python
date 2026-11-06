from __future__ import annotations

import io
import json
import os
import struct
import threading
from pathlib import Path

import pytest

from hai_agents_local.holotab import host
from hai_agents_local.holotab.endpoint import MAX_FRAME_BYTES, TcpEndpoint, UnixEndpoint

from .holotab_helpers import HELLO, WAIT_S, short_dir, tcp_link, unix_link


class Pipe(io.BytesIO):
    """A byte stream whose writes wake a waiting test, in place of a sleep."""

    def __init__(self) -> None:
        super().__init__()
        self.written = threading.Event()

    def write(self, data) -> int:
        self.written.set()
        return super().write(data)


def frame(message: object) -> bytes:
    payload = json.dumps(message).encode()
    return struct.pack("<I", len(payload)) + payload


@pytest.mark.parametrize("make_link", [unix_link, tcp_link])
def test_the_host_relays_chromes_frames_to_the_link_and_the_links_lines_to_chrome(make_link) -> None:
    if make_link is unix_link and os.name == "nt":
        pytest.skip("no Unix sockets")
    with short_dir() as folder:
        link = make_link(folder)
        link.start()
        read_end, write_end = os.pipe()
        stdout = Pipe()
        done: list[int] = []
        shim = threading.Thread(
            target=lambda: done.append(
                host.run_shim(os.fdopen(read_end, "rb"), stdout, link.endpoint, give_up_s=WAIT_S)
            )
        )
        shim.start()
        os.write(write_end, frame(HELLO))
        assert link.wait_connected(WAIT_S)

        link._send({"type": "LABEL_CHANNEL", "channel": "c", "title": "x" * MAX_FRAME_BYTES})
        link._send({"type": "STOP_CHANNEL", "channel": "c"})
        assert stdout.written.wait(WAIT_S)
        assert host.read_frame(io.BytesIO(stdout.getvalue())) == {
            "type": "STOP_CHANNEL",
            "channel": "c",
        }

        os.close(write_end)
        shim.join(WAIT_S)
        assert done == [0]
        link.close()


@pytest.mark.parametrize("make_endpoint", [UnixEndpoint, TcpEndpoint])
def test_the_host_tells_chrome_when_nothing_serves(make_endpoint) -> None:
    if make_endpoint is UnixEndpoint and os.name == "nt":
        pytest.skip("no Unix sockets")
    with short_dir() as folder:
        out = io.BytesIO()
        assert host.run_shim(io.BytesIO(), out, make_endpoint(Path(folder) / "none"), give_up_s=0) == 0
        assert host.read_frame(io.BytesIO(out.getvalue())) == {
            "type": "HOST_UNAVAILABLE",
            "reason": "no local process is serving HoloTab",
        }


def test_a_frame_over_chromes_one_megabyte_limit_is_refused_both_ways_with_its_size() -> None:
    assert MAX_FRAME_BYTES == 1024 * 1024
    with pytest.raises(ValueError, match=f"{MAX_FRAME_BYTES + 1} bytes exceeds Chrome's limit"):
        host.read_frame(io.BytesIO(struct.pack("<I", MAX_FRAME_BYTES + 1)))
    with pytest.raises(ValueError, match="exceeds Chrome's limit"):
        host.write_frame(io.BytesIO(), {"text": "x" * MAX_FRAME_BYTES})


def test_a_frame_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValueError, match="object"):
        host.read_frame(io.BytesIO(frame([1])))


def test_a_frame_cut_short_ends_the_stream() -> None:
    assert host.read_frame(io.BytesIO(struct.pack("<I", 9) + b"{}")) is None


def test_the_host_exits_without_python_finalizers(monkeypatch: pytest.MonkeyPatch) -> None:
    codes: list[int] = []

    def leave(code: int) -> None:
        codes.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(host.os, "_exit", leave)
    with open(os.devnull, "r+b") as null:
        monkeypatch.setattr(host.sys, "stdin", null)
        monkeypatch.setattr(host.sys, "stdout", null)
        monkeypatch.setattr(host, "run_shim", lambda: 0)
        with pytest.raises(SystemExit):
            host.main()

        def fail() -> int:
            raise RuntimeError("link broke")

        monkeypatch.setattr(host, "run_shim", fail)
        with pytest.raises(SystemExit):
            host.main()
    assert codes == [0, 1]

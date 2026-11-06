"""The native messaging host Chrome starts for the extension: it relays Chrome's framed stdio to the local link."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import sys
import threading
import time
from typing import IO, Any

from .endpoint import FRAME, MAX_FRAME_BYTES, Endpoint, default_endpoint, read_messages, send_line

logger = logging.getLogger(__name__)

CONNECT_RETRY_S = 2.0
CONNECT_GIVE_UP_S = 90.0


class FrameTooLarge(ValueError):
    def __init__(self, size: int) -> None:
        super().__init__(f"a native message of {size} bytes exceeds Chrome's limit of {MAX_FRAME_BYTES} bytes")


def read_frame(stream: IO[bytes]) -> dict[str, Any] | None:
    header = stream.read(FRAME.size)
    if len(header) < FRAME.size:
        return None
    (length,) = FRAME.unpack(header)
    if length > MAX_FRAME_BYTES:
        raise FrameTooLarge(length)
    payload = stream.read(length)
    if len(payload) < length:
        return None
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("native message must be a JSON object")
    return message


def write_frame(stream: IO[bytes], message: dict[str, Any]) -> None:
    payload = json.dumps(message).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameTooLarge(len(payload))
    stream.write(FRAME.pack(len(payload)) + payload)
    stream.flush()


def connect(
    endpoint: Endpoint, give_up_s: float = CONNECT_GIVE_UP_S, retry_s: float = CONNECT_RETRY_S
) -> socket.socket | None:
    deadline = time.monotonic() + give_up_s
    while True:
        try:
            return endpoint.open()
        except OSError:
            if time.monotonic() >= deadline:
                return None
            time.sleep(retry_s)


def run_shim(
    stdin: IO[bytes] | None = None,
    stdout: IO[bytes] | None = None,
    endpoint: Endpoint | None = None,
    give_up_s: float = CONNECT_GIVE_UP_S,
) -> int:
    stdin, stdout = stdin or sys.stdin.buffer, stdout or sys.stdout.buffer
    sock = connect(endpoint or default_endpoint(), give_up_s)
    if sock is None:
        write_frame(stdout, {"type": "HOST_UNAVAILABLE", "reason": "no local process is serving HoloTab"})
        return 0
    reader = sock.makefile("rb")

    def to_link() -> None:
        try:
            while (message := read_frame(stdin)) is not None:
                send_line(sock, message)
        except (OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    threading.Thread(target=to_link, daemon=True).start()
    try:
        for message in read_messages(reader):
            try:
                write_frame(stdout, message)
            except FrameTooLarge as exc:
                logger.warning("dropped a %s message for HoloTab: %s", message.get("type"), exc)
    except (OSError, ValueError):
        pass
    finally:
        reader.close()
        sock.close()
    return 0


def main() -> None:
    """Chrome keeps stdin open after the link's socket closes, so the exit skips interpreter shutdown."""
    if sys.platform == "win32":
        import msvcrt

        for stream in (sys.stdin, sys.stdout):
            msvcrt.setmode(stream.fileno(), os.O_BINARY)
    try:
        code = run_shim()
    except Exception:
        logger.exception("holotab native host failed")
        code = 1
    os._exit(code)


if __name__ == "__main__":
    main()

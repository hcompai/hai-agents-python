"""The local end of the HoloTab extension's native messaging: the endpoint its host shim relays to."""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .endpoint import Endpoint, default_endpoint

logger = logging.getLogger(__name__)

SERVE_TIMEOUT_S = 12.0


class HoloTabLink:
    """What the extension says (`HELLO`, `SERVING`, `STOPPED`, `ERROR`) and what this process asks of it
    (`SERVE_CHANNEL`, `LABEL_CHANNEL`, `STOP_CHANNEL`), over the one connection the shim holds open."""

    def __init__(self, endpoint: Endpoint | None = None) -> None:
        self.endpoint = endpoint or default_endpoint()
        self.extension: dict[str, Any] | None = None
        self.serving: dict[str, dict[str, Any]] = {}
        self.last_error: str | None = None
        self._conn: socket.socket | None = None
        self._lock = threading.Lock()
        self._arrived = threading.Condition(self._lock)
        self._acks: dict[str, threading.Event] = {}
        self._abandoned: set[str] = set()
        self._last: dict[str, dict[str, Any]] = {}
        self._server: socket.socket | None = None
        self._clients: set[socket.socket] = set()
        self._stopping = threading.Event()
        self._seen_at = 0.0

    @property
    def connected(self) -> bool:
        return self._conn is not None and self.extension is not None

    def seen_within(self, seconds: float) -> bool:
        """Connected now, or a moment ago: Chrome puts the extension's worker to sleep and wakes it every few
        minutes, and a gap of a few seconds is not a Chrome the user has lost."""
        return self.connected or (self._seen_at > 0 and time.monotonic() - self._seen_at < seconds)

    def wait_connected(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        with self._arrived:
            while not self.connected:
                left = deadline - time.monotonic()
                if left <= 0 or self._stopping.is_set():
                    return False
                self._arrived.wait(left)
        return True

    def start(self) -> None:
        if self._server is not None:
            return
        server = self.endpoint.bind()
        self._stopping.clear()
        self._server = server
        threading.Thread(target=self._accept_loop, args=(server,), name="holotab-link", daemon=True).start()

    def _accept_loop(self, server: socket.socket) -> None:
        while not self._stopping.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                break
            if self._stopping.is_set():
                conn.close()
                break
            with self._lock:
                self._clients.add(conn)
            threading.Thread(target=self._read_loop, args=(conn,), name="holotab-read", daemon=True).start()

    def _wake_accept(self) -> None:
        """A blocked accept() wakes for a connection, not for close() from another thread: knock once."""
        try:
            self.endpoint.connect().close()
        except OSError:
            pass

    def close(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._wake_accept()
        with self._lock:
            conn, server = self._conn, self._server
            clients = list(self._clients)
            self._conn = None
            self._server = None
            self._clients.clear()
            self.extension = None
            self.serving.clear()
            for event in self._acks.values():
                event.set()
            self._arrived.notify_all()
        for item in {*clients, conn, server}:
            if item is not None:
                self._hang_up(item)
        if server is not None:
            self.endpoint.release(server)

    @staticmethod
    def _hang_up(conn: socket.socket) -> None:
        """Ends the connection for its peer: a bare close() leaves it open while a `makefile` reader holds it."""
        with contextlib.suppress(OSError):
            conn.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            conn.close()

    def _read_loop(self, conn: socket.socket) -> None:
        active = False
        try:
            lines = conn.makefile("rb")
            greeting = None
            if self.endpoint.greeting_required:
                greeting = self._next_message(lines)
            if not self.endpoint.admits(conn, greeting):
                if self._stopping.is_set():
                    return
                logger.warning("refused a HoloTab link connection that is not this user's")
                return
            while (message := self._next_message(lines)) is not None:
                if not active:
                    if message.get("type") != "HELLO":
                        raise ValueError("HoloTab connection did not begin with HELLO")
                    with self._lock:
                        live = self._conn is not None
                        if not live:
                            self._conn = conn
                            self._seen_at = time.monotonic()
                    if live:
                        logger.info("refused a HoloTab connection while another one holds the link")
                        self._hang_up(conn)
                        return
                    active = True
                self._handle(message)
        except (OSError, ValueError) as exc:
            logger.info("holotab link closed: %s", exc)
        finally:
            conn.close()
            with self._lock:
                self._clients.discard(conn)
                if active and self._conn is conn:
                    self._conn = None
                    self.extension = None
                    self.serving.clear()
                    self._seen_at = time.monotonic()

    @staticmethod
    def _next_message(lines: Any) -> dict[str, Any] | None:
        for line in lines:
            if not line.strip():
                continue
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("HoloTab message must be a JSON object")
            return message
        return None

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        channel = str(message.get("channel") or "")
        if kind == "HELLO":
            self.last_error = None
            self.extension = {"id": message.get("extension"), "version": message.get("version")}
            logger.info("HoloTab %s connected (%s)", message.get("version"), message.get("extension"))
            with self._arrived:
                self._seen_at = time.monotonic()
                self._arrived.notify_all()
        elif kind == "SERVING":
            with self._lock:
                late = channel in self._abandoned
                self._abandoned.discard(channel)
            if late:
                logger.info("HoloTab served %s after its serve timed out; stopping it", channel)
                self.stop(channel)
                return
            self.last_error = None
            self.serving[channel] = message
            self._last[channel] = message
            self._acknowledge(channel)
        elif kind == "STOPPED":
            self.serving.pop(channel, None)
            self._last[channel] = message
            self._acknowledge(channel)
        elif kind == "ERROR":
            self.last_error = str(message.get("error") or "HoloTab reported an unknown error")
            logger.warning("HoloTab error: %s", self.last_error)
            with self._lock:
                self._abandoned.discard(channel)
                target = channel or (self._oldest_pending() if message.get("for") == "SERVE_CHANNEL" else "")
                event = self._acks.get(target)
                if event is not None:
                    self._last[target] = message
            if event is not None:
                event.set()
        elif kind == "HOST_UNAVAILABLE":
            self.last_error = str(message.get("reason") or "HoloTab could not reach the local link")
            logger.info("shim gave up: %s", self.last_error)

    def _oldest_pending(self) -> str:
        """The extension answers requests in order, so an error that names only its request type is the oldest
        serve still waiting. The caller holds the lock."""
        return next((channel for channel in self._acks if channel not in self._last), "")

    def _acknowledge(self, channel: str) -> None:
        if channel in self._acks:
            self._acks[channel].set()

    def _send(self, message: dict[str, Any]) -> bool:
        with self._lock:
            conn = self._conn
        if conn is None:
            self.last_error = "Chrome is not connected through the HoloTab extension"
            return False
        try:
            conn.sendall(json.dumps(message).encode("utf-8") + b"\n")
        except OSError as exc:
            logger.warning("holotab link send failed: %s", exc)
            self.last_error = "The HoloTab connection closed"
            return False
        return True

    def serve(
        self,
        channel: str,
        base_url: str,
        api_key: str,
        start_url: str | None = None,
        label: str = "",
        timeout_s: float = SERVE_TIMEOUT_S,
        client: str | None = None,
    ) -> dict[str, Any] | None:
        """Asks the extension to poll `base_url` for the channel's commands; its `SERVING` answer, or None.

        A `SERVING` that arrives after ``timeout_s`` is answered with `STOP_CHANNEL`, so the extension stops serving it."""
        if not channel or any(char in channel for char in "\r\n"):
            raise ValueError("channel must be a non-empty single-line identifier")
        if error := base_url_error(base_url):
            raise ValueError(error)
        if not api_key:
            raise ValueError("an API key is required to serve a Chrome channel")
        event = threading.Event()
        with self._lock:
            if channel in self._acks:
                raise RuntimeError(f"Chrome channel {channel!r} is already awaiting an acknowledgement")
            self._acks[channel] = event
            self._abandoned.discard(channel)
            self._last.pop(channel, None)
        self.last_error = None
        try:
            sent = self._send(
                {
                    "type": "SERVE_CHANNEL",
                    "channel": channel,
                    "base_url": base_url,
                    "api_key": api_key,
                    "start_url": start_url,
                    "label": label,
                    "client": client,
                }
            )
            if not sent:
                return None
            if not event.wait(timeout_s):
                with self._lock:
                    answered = event.is_set()
                    if not answered:
                        self._abandoned.add(channel)
                if not answered:
                    self.last_error = f"HoloTab did not acknowledge the Chrome channel within {timeout_s:g}s"
                    return None
            last = self._last.get(channel)
            if last and last.get("type") == "ERROR":
                return None
            return self.serving.get(channel)
        finally:
            with self._lock:
                self._acks.pop(channel, None)

    def relabel(self, channel: str, title: str) -> None:
        self._send({"type": "LABEL_CHANNEL", "channel": channel, "title": title})

    def stop(self, channel: str) -> None:
        self._send({"type": "STOP_CHANNEL", "channel": channel})


def base_url_error(base_url: str) -> str | None:
    parsed = urlsplit(str(base_url))
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return "base_url must not contain credentials, a query, or a fragment"
    if parsed.scheme == "https" and parsed.hostname:
        return None
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return None
    return "base_url must use HTTPS (HTTP is allowed only for localhost)"

"""The local end of the HoloTab extension's native messaging: the endpoint its host shim relays to."""

from __future__ import annotations

import contextlib
import json
import logging
import random
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .endpoint import Endpoint, EndpointBusy, default_endpoint

logger = logging.getLogger(__name__)

SERVE_TIMEOUT_S = 12.0
TAKEOVER_ATTEMPTS = 40
TAKEOVER_PAUSE_S = 0.25


class HoloTabLink:
    """What the extension says (`HELLO`, `SERVING`, `STOPPED`, `ERROR`) and what this process asks of it
    (`SERVE_CHANNEL`, `LABEL_CHANNEL`, `STOP_CHANNEL`).

    One process per user owns the endpoint and holds the connection the shim opens. Any other process attaches to the
    owner as a client: its requests go through the owner, and the owner relays the extension's answers about a channel
    back to the client that asked. When the owner exits, a client takes the endpoint over.
    """

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
        self._upstream: socket.socket | None = None
        self._peers: dict[socket.socket, set[str]] = {}
        self._channel_peer: dict[str, socket.socket] = {}
        self._wanted: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, float] = {}

    @property
    def role(self) -> str | None:
        if self._server is not None:
            return "owner"
        return "client" if self._upstream is not None else None

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

    def start(self, *, attach: bool = True) -> None:
        """Owns the endpoint, or with ``attach`` attaches to the process that does."""
        if self.role is not None:
            return
        self._stopping.clear()
        try:
            self._own()
        except EndpointBusy:
            if not attach:
                raise
            self._attach()

    def _own(self) -> None:
        server = self.endpoint.bind()
        self._server = server
        threading.Thread(target=self._accept_loop, args=(server,), name="holotab-link", daemon=True).start()

    def _attach(self) -> None:
        conn = self.endpoint.open()
        try:
            conn.sendall(json.dumps({"type": "ATTACH"}).encode("utf-8") + b"\n")
            with self._lock:
                if self._stopping.is_set():
                    raise OSError("the link is closing")
                self._upstream = self._conn = conn
        except OSError:
            conn.close()
            raise
        threading.Thread(target=self._client_loop, args=(conn,), name="holotab-client", daemon=True).start()

    def _client_loop(self, conn: socket.socket) -> None:
        try:
            lines = conn.makefile("rb")
            while (message := self._next_message(lines)) is not None:
                self._handle(message)
        except (OSError, ValueError) as exc:
            logger.info("holotab owner link closed: %s", exc)
        finally:
            conn.close()
            with self._lock:
                gone = self._upstream is conn
                if gone:
                    if self.extension is not None:
                        self._seen_at = time.monotonic()
                    self._upstream = self._conn = None
                    self.extension = None
                    self.serving.clear()
            if gone and not self._stopping.is_set():
                threading.Thread(target=self._take_over, name="holotab-takeover", daemon=True).start()

    def _take_over(self) -> None:
        """The owner exited: own the endpoint, or attach to whichever client got there first."""
        for _ in range(TAKEOVER_ATTEMPTS):
            if self._stopping.is_set():
                return
            try:
                with self._lock:
                    if self._stopping.is_set():
                        return
                    self._own()
                return
            except EndpointBusy:
                try:
                    self._attach()
                    return
                except OSError:
                    pass
            except OSError:
                pass
            time.sleep(TAKEOVER_PAUSE_S * (1 + random.random()))
        logger.warning("no process serves the HoloTab link and this one could not take it over")

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
            self._upstream = None
            self._peers.clear()
            self._channel_peer.clear()
            self._wanted.clear()
            self._pending.clear()
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
        active = peer = False
        try:
            lines = conn.makefile("rb")
            greeting = None
            if self.endpoint.greeting_required:
                greeting = self._next_message(lines)
            if not self.endpoint.admits(conn, greeting):
                if self._stopping.is_set() or (self.endpoint.greeting_required and greeting is None):
                    return
                logger.warning("refused a HoloTab link connection that is not this user's")
                return
            while (message := self._next_message(lines)) is not None:
                if not active and not peer and message.get("type") == "ATTACH":
                    peer = True
                    self._admit_peer(conn)
                    continue
                if peer:
                    self._handle_peer(conn, message)
                    continue
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
            if peer:
                self._drop_peer(conn)
            with self._lock:
                self._clients.discard(conn)
                lost = active and self._conn is conn
                if lost:
                    self._conn = None
                    self.extension = None
                    self.serving.clear()
                    self._seen_at = time.monotonic()
            if lost:
                self._tell_peers({"type": "EXTENSION_GONE"})

    def _admit_peer(self, conn: socket.socket) -> None:
        with self._lock:
            self._peers[conn] = set()
            extension = self.extension
        if extension is not None:
            self._send_to(conn, {"type": "HELLO", "extension": extension["id"], "version": extension["version"]})

    def _handle_peer(self, conn: socket.socket, message: dict[str, Any]) -> None:
        kind, channel = message.get("type"), str(message.get("channel") or "")
        if kind not in {"SERVE_CHANNEL", "LABEL_CHANNEL", "STOP_CHANNEL"} or not channel:
            return
        if kind == "SERVE_CHANNEL":
            with self._lock:
                self._peers.get(conn, set()).add(channel)
                self._channel_peer[channel] = conn
        if not self._send(message) and kind == "SERVE_CHANNEL":
            self._send_to(conn, {"type": "ERROR", "channel": channel, "error": self.last_error})

    def _drop_peer(self, conn: socket.socket) -> None:
        with self._lock:
            channels = self._peers.pop(conn, set())
            for channel in channels:
                self._channel_peer.pop(channel, None)
                self._pending.pop(channel, None)
        for channel in channels:
            self.stop(channel)

    def _tell_peers(self, message: dict[str, Any]) -> None:
        with self._lock:
            peers = list(self._peers)
        for peer in peers:
            self._send_to(peer, message)

    def _relay(self, message: dict[str, Any]) -> None:
        channel = str(message.get("channel") or "")
        with self._lock:
            peer = self._channel_peer.get(channel)
            if peer is not None and message.get("type") in {"STOPPED", "ERROR"}:
                self._peers.get(peer, set()).discard(channel)
                self._channel_peer.pop(channel, None)
        if peer is not None:
            self._send_to(peer, message)

    @staticmethod
    def _send_to(conn: socket.socket, message: dict[str, Any]) -> bool:
        try:
            conn.sendall(json.dumps(message).encode("utf-8") + b"\n")
        except OSError:
            return False
        return True

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
            self._tell_peers(message)
            self._resume()
        elif kind == "EXTENSION_GONE":
            with self._lock:
                self.extension = None
                self.serving.clear()
                self._seen_at = time.monotonic()
        elif kind == "SERVING":
            with self._lock:
                self._pending.pop(channel, None)
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
            self._relay(message)
        elif kind == "STOPPED":
            with self._lock:
                self._pending.pop(channel, None)
            self.serving.pop(channel, None)
            self._wanted.pop(channel, None)
            self._last[channel] = message
            self._acknowledge(channel)
            self._relay(message)
        elif kind == "ERROR":
            self.last_error = str(message.get("error") or "HoloTab reported an unknown error")
            logger.warning("HoloTab error: %s", self.last_error)
            with self._lock:
                target = channel or (self._oldest_pending() if message.get("for") == "SERVE_CHANNEL" else "")
                self._abandoned.discard(target)
                self._pending.pop(target, None)
                event = self._acks.get(target)
                if event is not None:
                    self._last[target] = message
            if event is not None:
                event.set()
            self._relay({**message, "channel": target} if target and not channel else message)
        elif kind == "HOST_UNAVAILABLE":
            self.last_error = str(message.get("reason") or "HoloTab could not reach the local link")
            logger.info("shim gave up: %s", self.last_error)

    def _oldest_pending(self) -> str:
        """The extension answers requests in order, so an error that names only its request type is the oldest
        serve still waiting, this process's or a client's. The caller holds the lock."""
        now = time.monotonic()
        for channel, sent_at in list(self._pending.items()):
            if channel in self._acks or now - sent_at < SERVE_TIMEOUT_S:
                return channel
            del self._pending[channel]
        return ""

    def _resume(self) -> None:
        """A channel this process asked for and the extension no longer serves is asked for again."""
        for channel, request in list(self._wanted.items()):
            if channel not in self.serving and channel not in self._acks:
                self._send(request)

    def _acknowledge(self, channel: str) -> None:
        if channel in self._acks:
            self._acks[channel].set()

    def _send(self, message: dict[str, Any]) -> bool:
        serve = str(message.get("channel") or "") if message.get("type") == "SERVE_CHANNEL" else ""
        with self._lock:
            conn = self._conn
            if conn is not None and serve:
                self._pending.pop(serve, None)
                self._pending[serve] = time.monotonic()
        if conn is None:
            self.last_error = "Chrome is not connected through the HoloTab extension"
            return False
        try:
            conn.sendall(json.dumps(message).encode("utf-8") + b"\n")
        except OSError as exc:
            logger.warning("holotab link send failed: %s", exc)
            self.last_error = "The HoloTab connection closed"
            with self._lock:
                self._pending.pop(serve, None)
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
            request = {
                "type": "SERVE_CHANNEL",
                "channel": channel,
                "base_url": base_url,
                "api_key": api_key,
                "start_url": start_url,
                "label": label,
                "client": client,
            }
            if not self._send(request):
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
            if served := self.serving.get(channel):
                self._wanted[channel] = request
            return served
        finally:
            with self._lock:
                self._acks.pop(channel, None)

    def relabel(self, channel: str, title: str) -> None:
        self._send({"type": "LABEL_CHANNEL", "channel": channel, "title": title})

    def stop(self, channel: str) -> None:
        self._wanted.pop(channel, None)
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

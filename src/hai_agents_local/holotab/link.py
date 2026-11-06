"""The local end of the HoloTab extension's native messaging: the endpoint its host shim relays to."""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, wait
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .endpoint import Endpoint, default_endpoint, read_messages, send_line

logger = logging.getLogger(__name__)

SERVE_TIMEOUT_S = 12.0
HOLOTAB_PROTOCOL = 1
CONSENT_WAIT_S = 120.0
CONSENT_MARGIN_S = 5.0
TOO_OLD = "HoloTab is too old for this SDK: update it from the Chrome Web Store"
DISCONNECTED = "HoloTab disconnected before it answered"


class HoloTabRefused(RuntimeError):
    """HoloTab did not serve a channel; ``code`` is the extension's, such as `DENIED` when the user refused the app."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class HoloTabLink:
    """What the extension says (`HELLO`, `CONSENT_PENDING`, `SERVING`, `STOPPED`, `ERROR`) and what this process asks
    of it (`SERVE_CHANNEL`, `LABEL_CHANNEL`, `STOP_CHANNEL`), over the one connection the shim holds open.

    The first HoloTab that says HELLO holds the link, whichever Chrome profile it runs in; another one is refused
    until that connection ends."""

    def __init__(self, endpoint: Endpoint | None = None) -> None:
        self.endpoint = endpoint or default_endpoint()
        self.extension: dict[str, Any] | None = None
        self.serving: dict[str, dict[str, Any]] = {}
        self.incompatible: str | None = None
        self._conn: socket.socket | None = None
        self._lock = threading.Lock()
        self._arrived = threading.Condition(self._lock)
        self._answers: dict[str, Future[dict[str, Any]]] = {}
        self._abandoned: set[str] = set()
        self._server: socket.socket | None = None
        self._clients: set[socket.socket] = set()
        self._stopping = threading.Event()
        self._seen_at = 0.0
        self._consent_until: dict[str, float] = {}
        self._on_stopped: dict[str, Callable[[str], None]] = {}
        self._wanted: dict[str, dict[str, Any]] = {}

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
            self._wanted.clear()
            self._fail_waiting("the HoloTab link closed")
            self._arrived.notify_all()
        for item in {*clients, conn, server}:
            if item is not None:
                self._hang_up(item)
        if server is not None:
            self.endpoint.release()

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
            if not self.endpoint.admits(conn):
                if not self._stopping.is_set():
                    logger.warning("refused a HoloTab link connection that is not this user's")
                return
            for message in read_messages(conn.makefile("rb")):
                if not active:
                    if message.get("type") != "HELLO":
                        raise ValueError("HoloTab connection did not begin with HELLO")
                    if not speaks_protocol(message):
                        self.incompatible = TOO_OLD
                        logger.warning("refused HoloTab %s: %s", message.get("version"), TOO_OLD)
                        return
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
                    self._fail_waiting(DISCONNECTED)

    def _fail_waiting(self, reason: str) -> None:
        """Every serve still waiting for an answer ends now with ``reason``. The caller holds the lock."""
        for channel in self._answers:
            self._answer(channel, {"type": "ERROR", "channel": channel, "error": reason})

    def _answer(self, channel: str, message: dict[str, Any]) -> None:
        """Ends the wait of the serve of ``channel``, if one waits. The caller holds the lock."""
        answer = self._answers.get(channel)
        if answer is not None and not answer.done():
            answer.set_result(message)

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        channel = str(message.get("channel") or "")
        if kind == "HELLO":
            self.incompatible = None
            self.extension = {"id": message.get("extension"), "version": message.get("version")}
            logger.info("HoloTab %s connected (%s)", message.get("version"), message.get("extension"))
            with self._arrived:
                self._seen_at = time.monotonic()
                self._arrived.notify_all()
            self._resume()
        elif kind == "CONSENT_PENDING":
            with self._lock:
                waiting = channel in self._answers
                if waiting:
                    self._consent_until[channel] = time.monotonic() + CONSENT_WAIT_S + CONSENT_MARGIN_S
            if waiting:
                logger.warning(
                    "Allow %s in HoloTab's side panel: it waits up to %ds for your answer",
                    message.get("client") or "this app",
                    CONSENT_WAIT_S,
                )
        elif kind == "SERVING":
            with self._lock:
                late = channel in self._abandoned
                self._abandoned.discard(channel)
            if late:
                logger.info("HoloTab served %s after its serve timed out; stopping it", channel)
                self.stop(channel)
                return
            self.serving[channel] = message
            with self._lock:
                self._answer(channel, message)
        elif kind == "STOPPED":
            self.serving.pop(channel, None)
            self._wanted.pop(channel, None)
            with self._lock:
                self._answer(channel, message)
                on_stopped = self._on_stopped.pop(channel, None)
            if on_stopped is not None:
                reason = str(message.get("reason") or "stopped")
                logger.warning("HoloTab stopped serving %s on its own (%s)", channel, reason)
                on_stopped(reason)
        elif kind == "ERROR":
            logger.warning("HoloTab error on %s: %s", channel or "the link", message.get("error"))
            with self._lock:
                self._abandoned.discard(channel)
                self._answer(channel, message)

    def _resume(self) -> None:
        """A channel this process asked for and the extension no longer serves is asked for again."""
        for channel, request in list(self._wanted.items()):
            if channel not in self.serving and channel not in self._answers:
                with contextlib.suppress(HoloTabRefused):
                    self._send(request)

    def _send(self, message: dict[str, Any]) -> None:
        """Raises `HoloTabRefused` when the message cannot reach the extension."""
        with self._lock:
            conn = self._conn
        if conn is None:
            raise HoloTabRefused("Chrome is not connected through the HoloTab extension")
        try:
            send_line(conn, message)
        except OSError as exc:
            logger.warning("holotab link send failed: %s", exc)
            raise HoloTabRefused("The HoloTab connection closed") from exc

    def serve(
        self,
        channel: str,
        base_url: str,
        api_key: str,
        start_url: str | None = None,
        label: str = "",
        timeout_s: float = SERVE_TIMEOUT_S,
        client: str | None = None,
        upload_roots: Sequence[str] | None = None,
        on_stopped: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Asks the extension to poll `base_url` for the channel's commands; its `SERVING` answer, else
        `HoloTabRefused` with the reason.

        `CONSENT_PENDING` extends the wait to ``CONSENT_WAIT_S`` while the user answers in HoloTab. A `SERVING` that
        arrives after the wait is answered with `STOP_CHANNEL`, so the extension stops serving it. ``upload_roots``
        are the folders HoloTab may upload files from. ``on_stopped`` is called with the reason when HoloTab stops
        the channel without being asked."""
        if not channel or any(char in channel for char in "\r\n"):
            raise ValueError("channel must be a non-empty single-line identifier")
        if error := base_url_error(base_url):
            raise ValueError(error)
        if not api_key:
            raise ValueError("an API key is required to serve a Chrome channel")
        if self.incompatible and not self.connected:
            raise HoloTabRefused(self.incompatible)
        answer: Future[dict[str, Any]] = Future()
        with self._lock:
            if channel in self._answers:
                raise RuntimeError(f"Chrome channel {channel!r} is already awaiting an acknowledgement")
            self._answers[channel] = answer
            self._abandoned.discard(channel)
        try:
            request: dict[str, Any] = {
                "type": "SERVE_CHANNEL",
                "channel": channel,
                "base_url": base_url,
                "api_key": api_key,
                "start_url": start_url,
                "label": label,
                "client": client,
            }
            if upload_roots is not None:
                request["upload_roots"] = [str(Path(root).expanduser().resolve()) for root in upload_roots]
            self._send(request)
            message = self._await(channel, answer, timeout_s)
            if message.get("type") == "ERROR":
                raise HoloTabRefused(
                    str(message.get("error") or "HoloTab reported an unknown error"), message.get("code")
                )
            if message.get("type") != "SERVING":
                raise HoloTabRefused("HoloTab did not serve the Chrome channel")
            self._wanted[channel] = request
            if on_stopped is not None:
                with self._lock:
                    self._on_stopped[channel] = on_stopped
            return message
        finally:
            with self._lock:
                self._answers.pop(channel, None)
                self._consent_until.pop(channel, None)

    def _await(self, channel: str, answer: Future[dict[str, Any]], timeout_s: float) -> dict[str, Any]:
        """The extension's answer; a `CONSENT_PENDING` moves the deadline."""
        started = time.monotonic()
        deadline = started + timeout_s
        while not wait([answer], max(deadline - time.monotonic(), 0.0)).done:
            with self._lock:
                if answer.done():
                    break
                extended = self._consent_until.get(channel, 0.0)
                if extended <= deadline:
                    self._abandoned.add(channel)
                    raise HoloTabRefused(
                        f"HoloTab did not acknowledge the Chrome channel within {deadline - started:g}s"
                    )
                deadline = extended
        return answer.result()

    def relabel(self, channel: str, title: str) -> None:
        with contextlib.suppress(HoloTabRefused):
            self._send({"type": "LABEL_CHANNEL", "channel": channel, "title": title})

    def stop(self, channel: str) -> None:
        """Asks the extension to stop the channel; a serve still waiting for it ends at once."""
        self._wanted.pop(channel, None)
        with self._lock:
            self._on_stopped.pop(channel, None)
            answer = self._answers.get(channel)
            if answer is not None and not answer.done():
                self._abandoned.add(channel)
                answer.set_result({"type": "ERROR", "channel": channel, "error": "the channel was stopped"})
        with contextlib.suppress(HoloTabRefused):
            self._send({"type": "STOP_CHANNEL", "channel": channel})


def speaks_protocol(hello: dict[str, Any]) -> bool:
    protocol = hello.get("protocol")
    return isinstance(protocol, int) and not isinstance(protocol, bool) and protocol >= HOLOTAB_PROTOCOL


def base_url_error(base_url: str) -> str | None:
    parsed = urlsplit(str(base_url))
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return "base_url must not contain credentials, a query, or a fragment"
    if parsed.scheme == "https" and parsed.hostname:
        return None
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return None
    return "base_url must use HTTPS (HTTP is allowed only for localhost)"

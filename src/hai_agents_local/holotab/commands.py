"""The platform's command contract served on loopback, so the HoloTab extension can be driven from this process.

The extension long-polls `{base_url}/api/v1/commands/{session}/commands` for work and posts each result back, so
serving that contract on 127.0.0.1 makes it answer to this process, with the platform out of the path.
"""

from __future__ import annotations

import json
import logging
import secrets
import select
import socket
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

MAX_HOLD_S = 25.0
SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S = 60.0
DEFAULT_COMMAND_TIMEOUT_S = SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S - 10.0
MAX_BODY_BYTES = 32 * 1024 * 1024


class LocalCommandServer:
    """Serves the command contract on 127.0.0.1 behind one bearer token, so the extension can be driven from here."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.token = secrets.token_urlsafe(32)
        self._queue: deque[dict[str, Any]] = deque()
        self._results: dict[str, tuple[Any, str | None]] = {}
        self._waiters: dict[str, threading.Event] = {}
        self._arrived = threading.Condition()
        self._polls = 0
        self._failure: str | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("the local command server is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> str:
        if self._server is not None:
            return self.base_url
        server = _QuietServer(("127.0.0.1", 0), _handler_for(self))
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="chrome-commands", daemon=True)
        self._thread.start()
        logger.info("local Chrome command server on %s", self.base_url)
        return self.base_url

    def stop(self) -> None:
        with self._arrived:
            server, self._server = self._server, None
            waiters = list(self._waiters.values())
            self._arrived.notify_all()
        for event in waiters:
            event.set()
        if server is not None:
            server.shutdown()
            server.server_close()

    def fail(self, reason: str) -> None:
        """Every command still waiting, and every later one, fails at once with ``reason``: Chrome will not answer."""
        with self._arrived:
            self._failure = reason
            self._queue.clear()
            waiters = list(self._waiters.values())
            self._arrived.notify_all()
        for event in waiters:
            event.set()

    def submit(
        self, name: str, args: dict[str, Any] | None = None, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S
    ) -> Any:
        """Queues one command for the extension and waits for its result; a page's error is raised, never returned.

        The default wait ends before the agent's own command timeout, so a command the agent gave up on is never
        left queued for the extension to run later."""
        try:
            json.dumps(args or {})
        except (TypeError, ValueError) as exc:
            raise TypeError(f"the arguments of {name} cannot be sent to Chrome: {exc}") from exc
        command_id = str(uuid.uuid4())
        event = threading.Event()
        with self._arrived:
            if self._failure is not None:
                raise RuntimeError(self._failure)
            if self._server is None:
                raise RuntimeError("the local command server is not running")
            self._waiters[command_id] = event
            self._queue.append({"id": command_id, "command_uid": command_id, "name": name, "args": dict(args or {})})
            self._arrived.notify_all()
        try:
            if not event.wait(timeout_s):
                raise RuntimeError(f"Chrome did not answer {name} within {timeout_s:g}s")
            if command_id not in self._results:
                raise RuntimeError(self._failure or f"the local command server stopped before Chrome answered {name}")
            result, error = self._results.pop(command_id)
            if error:
                raise RuntimeError(error)
            return result
        finally:
            with self._arrived:
                self._queue = deque(queued for queued in self._queue if queued["id"] != command_id)
                self._waiters.pop(command_id, None)
                self._results.pop(command_id, None)

    def take(self, session_id: str, wait_for_seconds: float) -> list[dict[str, Any]]:
        """What is queued, holding the connection open until there is something or the time is up.

        A newer poll supersedes the ones still waiting, which answer empty: the extension starts a new poll after
        dropping one, and the dropped one must not take the next command."""
        if session_id != self.session_id:
            return []
        deadline = time.monotonic() + min(max(wait_for_seconds, 0.0), MAX_HOLD_S)
        with self._arrived:
            self._polls += 1
            poll = self._polls
            self._arrived.notify_all()
            while not self._queue and self._server is not None and poll == self._polls:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._arrived.wait(remaining)
            if poll != self._polls:
                return []
            taken, self._queue = list(self._queue), deque()
        return taken

    def requeue(self, commands: list[dict[str, Any]]) -> None:
        """Puts back, in order and ahead of the rest, what a poll took but could not deliver."""
        with self._arrived:
            self._queue.extendleft(reversed([command for command in commands if command["id"] in self._waiters]))
            self._arrived.notify_all()

    def deliver(self, command_id: str, payload: dict[str, Any]) -> bool:
        with self._arrived:
            event = self._waiters.get(command_id)
            if event is None:
                logger.debug("result for an unknown or abandoned command %s", command_id)
                return False
            self._results[command_id] = (payload.get("result"), payload.get("error"))
        event.set()
        return True

    def authorised(self, header: str | None) -> bool:
        expected = f"Bearer {self.token}".encode()
        return bool(header) and secrets.compare_digest(str(header).encode("utf-8", "surrogateescape"), expected)


class _QuietServer(ThreadingHTTPServer):
    """A poll the extension drops resets its connection: that is routine, not a traceback on stderr."""

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):
            logger.debug("a Chrome command connection from %s reset", client_address)
            return
        super().handle_error(request, client_address)


def _left(conn: socket.socket) -> bool:
    """Whether the client already closed the connection a poll is about to answer on."""
    try:
        readable, _, _ = select.select([conn], [], [], 0)
        return bool(readable) and conn.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


def _handler_for(owner: LocalCommandServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "HaiLocalChrome/1"

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _route(self, suffix: str) -> str | None:
            """The id in `/api/v1/commands/{id}/{suffix}` once the token checks out; None once refused."""
            if not owner.authorised(self.headers.get("Authorization")):
                self._send(401, {"error": "unauthorised"})
                return None
            pieces = [piece for piece in urlparse(self.path).path.split("/") if piece]
            if len(pieces) != 5 or pieces[:3] != ["api", "v1", "commands"] or pieces[4] != suffix:
                self._send(404, {"error": "no such endpoint"})
                return None
            return pieces[3]

        def do_GET(self) -> None:
            if (session_id := self._route("commands")) is None:
                return
            try:
                wait = float(parse_qs(urlparse(self.path).query).get("wait_for_seconds", ["0"])[0])
            except ValueError:
                wait = 0.0
            if commands := owner.take(session_id, wait):
                try:
                    if _left(self.connection):
                        raise ConnectionResetError("the poll left before its commands were sent")
                    self._send(200, commands)
                except OSError:
                    owner.requeue(commands)
                    self.close_connection = True
                return
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            if (command_id := self._route("result")) is None:
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send(400, {"error": "bad length"})
                return
            if length < 0:
                self._send(400, {"error": "bad length"})
                return
            if length > MAX_BODY_BYTES:
                self._send(413, {"error": "result too large"})
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (OSError, ValueError):
                self._send(400, {"error": "bad body"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"error": "a result must be an object"})
                return
            owner.deliver(command_id, payload)
            self._send(200, {"ok": True})

        def _send(self, status: int, body: Any) -> None:
            """An error closes the connection: a body it did not read must not be parsed as the next request."""
            encoded = json.dumps(body).encode()
            if status >= 400:
                self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            if status >= 400:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)

    return Handler

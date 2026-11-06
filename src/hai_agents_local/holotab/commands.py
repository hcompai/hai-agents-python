"""The platform's command contract served on loopback, so the HoloTab extension can be driven from this process.

The extension long-polls `{base_url}/api/v1/commands/{session}/commands` for work and posts each result back, so
serving that contract on 127.0.0.1 makes it answer to this process, with the platform out of the path.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

MAX_HOLD_S = 25.0
DEFAULT_COMMAND_TIMEOUT_S = 90.0
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
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        server.daemon_threads = True
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

    def submit(
        self, name: str, args: dict[str, Any] | None = None, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S
    ) -> Any:
        """Queues one command for the extension and waits for its result; a page's error is raised, never returned."""
        try:
            json.dumps(args or {})
        except (TypeError, ValueError) as exc:
            raise TypeError(f"the arguments of {name} cannot be sent to Chrome: {exc}") from exc
        command_id = str(uuid.uuid4())
        event = threading.Event()
        with self._arrived:
            if self._server is None:
                raise RuntimeError("the local command server is not running")
            self._waiters[command_id] = event
            self._queue.append({"id": command_id, "command_uid": command_id, "name": name, "args": dict(args or {})})
            self._arrived.notify_all()
        try:
            if not event.wait(timeout_s):
                raise RuntimeError(f"Chrome did not answer {name} within {timeout_s:g}s")
            if command_id not in self._results:
                raise RuntimeError(f"the local command server stopped before Chrome answered {name}")
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
        """What is queued, holding the connection open until there is something or the time is up."""
        if session_id != self.session_id:
            return []
        deadline = time.monotonic() + min(max(wait_for_seconds, 0.0), MAX_HOLD_S)
        with self._arrived:
            while not self._queue and self._server is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._arrived.wait(remaining)
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
        return bool(header) and secrets.compare_digest(str(header), f"Bearer {self.token}")


def _handler_for(owner: LocalCommandServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "HaiLocalChrome/1"

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def do_GET(self) -> None:
            if not owner.authorised(self.headers.get("Authorization")):
                self._send(401, {"error": "unauthorised"})
                return
            parts = urlparse(self.path)
            pieces = [piece for piece in parts.path.split("/") if piece]
            if len(pieces) != 5 or pieces[:3] != ["api", "v1", "commands"] or pieces[4] != "commands":
                self._send(404, {"error": "no such endpoint"})
                return
            try:
                wait = float(parse_qs(parts.query).get("wait_for_seconds", ["0"])[0])
            except ValueError:
                wait = 0.0
            if commands := owner.take(pieces[3], wait):
                try:
                    self._send(200, commands)
                except OSError:
                    owner.requeue(commands)
                    self.close_connection = True
                return
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            if not owner.authorised(self.headers.get("Authorization")):
                self._send(401, {"error": "unauthorised"})
                return
            pieces = [piece for piece in urlparse(self.path).path.split("/") if piece]
            if len(pieces) != 5 or pieces[:3] != ["api", "v1", "commands"] or pieces[4] != "result":
                self._send(404, {"error": "no such endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
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
            owner.deliver(pieces[3], payload)
            self._send(200, {"ok": True})

        def _send(self, status: int, body: Any) -> None:
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler

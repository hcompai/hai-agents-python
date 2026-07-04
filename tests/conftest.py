"""Shared offline fixtures: an executable fake hai-agent-runtime."""

from __future__ import annotations

import pathlib
import socket

import pytest

FAKE_RUNTIME_SOURCE = '''#!/usr/bin/env python3
"""Stand-in hai-agent-runtime: /health plus a bearer-checked empty sessions list.

Reads the same spawn env contract as the real binary: HAI_AGENT_RUNTIME_PORT and
HAI_AGENT_RUNTIME_API_TOKEN (crashes loudly if the SDK failed to pass them).
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ["HAI_AGENT_RUNTIME_PORT"])
TOKEN = os.environ["HAI_AGENT_RUNTIME_API_TOKEN"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            # env echo (HAI_-prefixed only) lets tests assert what the SDK spawn passed us.
            hai_env = {k: v for k, v in os.environ.items() if k.startswith("HAI_")}
            self._reply(200, {"status": "ok", "version": "0.0.0-fake", "env": hai_env})
        elif self.path.startswith("/api/v2/sessions"):
            if self.headers.get("Authorization") != "Bearer " + TOKEN:
                self._reply(401, {"detail": "invalid token"})
            else:
                self._reply(200, {"items": [], "total": 0, "page": 1})
        else:
            self._reply(404, {"detail": "not found"})

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(fmt % args, file=sys.stderr)


print("fake runtime listening on", PORT, file=sys.stderr)
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
'''


@pytest.fixture
def fake_binary(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "hai-agent-runtime"
    path.write_text(FAKE_RUNTIME_SOURCE)
    path.chmod(0o755)
    return path


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Self

from hai_agents_local.holotab.commands import LocalCommandServer


class FakeExtension:
    """Polls and answers exactly as the extension's executor does, so the contract is tested rather than described."""

    def __init__(self, server: LocalCommandServer, answers: dict[str, object]) -> None:
        self.server = server
        self.answers = answers
        self.seen: list[str] = []
        self.args: dict[str, dict] = {}
        self._stop = threading.Event()
        self._headers = {"Authorization": f"Bearer {server.token}", "Content-Type": "application/json"}
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                base_url = self.server.base_url
            except RuntimeError:
                self._stop.wait(0.01)
                continue
            url = f"{base_url}/api/v1/commands/{self.server.session_id}/commands?wait_for_seconds=1"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=self._headers), timeout=5) as page:
                    if page.status == 204:
                        continue
                    commands = json.loads(page.read())
            except (OSError, ValueError):
                continue
            for command in commands:
                self.seen.append(command["name"])
                self.args[command["name"]] = command["args"]
                known = command["name"] in self.answers
                body = json.dumps(
                    {
                        "result": self.answers.get(command["name"]),
                        "error": None if known else f"{command['name']} is not supported",
                        "command_uid": command["command_uid"],
                    }
                ).encode()
                result_url = f"{base_url}/api/v1/commands/{command['id']}/result"
                request = urllib.request.Request(result_url, data=body, headers=self._headers, method="POST")
                with urllib.request.urlopen(request, timeout=5):
                    pass

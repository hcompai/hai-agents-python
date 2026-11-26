from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx
import pytest

from hai_agents_local import WorkstationBridge
from hai_agents_local.config import shell_sandbox
from hai_agents_local.connections import load_connections

SERVER = """\
from mcp.server.fastmcp import FastMCP
import os
server = FastMCP("notes")
@server.tool()
def add(a: int, b: int) -> str:
    return f"{a + b} {os.environ['NOTES_KEY']}"
server.run()
"""


def test_connections_fill_their_keys_and_leave_out_what_they_cannot(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("LINEAR_KEY", "from-env")
    config = tmp_path / ".config" / "hai"
    config.mkdir(parents=True)
    (config / ".env").write_text("NOTION_KEY=stored\n")
    servers = {
        "linear": {"url": "https://mcp.linear.app/mcp", "headers": {"Authorization": "Bearer ${env:LINEAR_KEY}"}},
        "notion": {"type": "sse", "url": "https://n/sse", "headers": {"Authorization": "Bearer ${NOTION_KEY}"}},
        "files": {"command": "npx", "args": ["-y", "server", "~/docs"], "env": {"TOKEN": "${LINEAR_KEY}"}},
        "unset": {"url": "https://u/mcp", "headers": {"Authorization": "${NOWHERE}"}},
        "dotted.name": {"url": "https://d/mcp"},
    }
    (config / "mcp.json").write_text(json.dumps({"mcpServers": servers}))

    with caplog.at_level(logging.WARNING):
        found = {connection.name: connection for connection in load_connections()}

    assert list(found) == ["linear", "notion", "files"]
    assert found["linear"].headers == {"Authorization": "Bearer from-env"} and found["linear"].transport == "http"
    assert found["notion"].headers == {"Authorization": "Bearer stored"} and found["notion"].transport == "sse"
    assert found["files"].env == {"TOKEN": "from-env"} and found["files"].variables == {"LINEAR_KEY"}
    assert "NOWHERE" in caplog.text and "dotted.name" in caplog.text


@pytest.mark.skipif(os.name == "nt", reason="the stand-in srt is a shell script")
def test_a_shell_desktop_reaches_its_mcp_servers_through_the_resolver_alone(tmp_path, monkeypatch):
    pytest.importorskip("hai_drivers.code_sandbox.local.sandbox_runtime")
    from hai_agents_local import mcporter, workstation

    srt = tmp_path / "bin" / "srt"
    srt.parent.mkdir()
    srt.write_text('#!/bin/sh\nSRT_SETTINGS="$2" exec bash -c "$4"\n')
    srt.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([str(srt.parent), os.defpath]))
    monkeypatch.setenv("NOTES_KEY", "secret-key")
    monkeypatch.setattr(workstation, "shell_sandbox", shell_sandbox)
    monkeypatch.setattr(workstation, "_host_cua", lambda environment: {})
    monkeypatch.setattr(mcporter, "mcporter", lambda: None)
    script = tmp_path / "notes.py"
    script.write_text(SERVER)
    config = tmp_path / ".config" / "hai"
    config.mkdir(parents=True)
    notes = {"command": sys.executable, "args": [str(script)], "env": {"NOTES_KEY": "${NOTES_KEY}"}}
    (config / "mcp.json").write_text(json.dumps({"mcpServers": {"notes": notes}}))

    bridge = WorkstationBridge(api_key="k", workspace=str(tmp_path / "workspace"))
    with bridge.create_driver() as driver:
        rules = json.loads(Path(driver.execute('echo "$SRT_SETTINGS"').stdout.strip()).read_text())
        shim = driver.execute("command -v mcporter").stdout.strip()
        shown = Path(driver.execute('echo "$MCPORTER_CONFIG"').stdout.strip()).read_text()
    resolver = bridge._resolver
    assert resolver is not None
    assert resolver.host in rules["network"]["allowedDomains"]
    assert str(config / "mcp.json") in rules["filesystem"]["denyRead"]
    assert {"name": "NOTES_KEY", "mode": "deny"} in rules["credentials"]["envVars"]
    assert Path(shim).parent != srt.parent and "secret-key" not in shown
    served = json.loads(shown)["mcpServers"]["notes"]
    url, headers = served["baseUrl"], served["headers"]

    assert asyncio.run(_call(url, headers, "add", {"a": 2, "b": 3})) == "5 secret-key"
    assert httpx.post(url, json={}).status_code == 401

    bridge._stop_connections()
    assert bridge._resolver is None
    with pytest.raises(httpx.ConnectError):
        httpx.post(url, json={}, headers=headers)


async def _call(url: str, headers: dict[str, str], tool: str, arguments: dict[str, object]) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with (
        httpx.AsyncClient(headers=headers) as client,
        streamable_http_client(url, http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments)
    return result.content[0].text

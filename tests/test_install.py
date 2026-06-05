from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hai_agents_cli import hosts
from hai_agents_cli.app import app
from hai_agents_cli.hosts import Client, Status, unwire_mcp, wire_mcp

runner = CliRunner()
MCP_PATH = "/opt/venv/bin/hai-mcp"


@pytest.fixture(autouse=True)
def _stub_resolve(monkeypatch) -> None:
    monkeypatch.setattr(hosts, "resolve_mcp_command", lambda: MCP_PATH)


def _cursor_host(path) -> Client:
    return Client(
        name="Test",
        config_path=str(path),
        key_path=("mcpServers", "hai"),
        leaf={"type": "stdio", "command": hosts.MCP_BINARY},
    )


def test_wire_merges_and_preserves_siblings(tmp_path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "keep-me"}}}))
    host = _cursor_host(cfg)

    status, _ = wire_mcp(host)

    assert status is Status.INSTALLED
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["other"] == {"command": "keep-me"}
    assert data["mcpServers"]["hai"] == {"type": "stdio", "command": MCP_PATH}


def test_wire_is_idempotent(tmp_path) -> None:
    host = _cursor_host(tmp_path / "mcp.json")
    assert wire_mcp(host)[0] is Status.INSTALLED
    assert wire_mcp(host)[0] is Status.SKIPPED


def test_wire_creates_missing_config(tmp_path) -> None:
    host = _cursor_host(tmp_path / "nested" / "mcp.json")
    assert wire_mcp(host)[0] is Status.INSTALLED
    assert (tmp_path / "nested" / "mcp.json").exists()


def test_unwire_removes_only_our_leaf(tmp_path) -> None:
    cfg = tmp_path / "mcp.json"
    host = _cursor_host(cfg)
    wire_mcp(host)
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "keep"}, "hai": {"command": MCP_PATH}}}))

    status, _ = unwire_mcp(host)

    assert status is Status.REMOVED
    data = json.loads(cfg.read_text())
    assert "hai" not in data["mcpServers"]
    assert data["mcpServers"]["other"] == {"command": "keep"}


def test_unwire_absent_is_skipped(tmp_path) -> None:
    assert unwire_mcp(_cursor_host(tmp_path / "mcp.json"))[0] is Status.SKIPPED


def test_wire_rejects_invalid_json(tmp_path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{not json")
    assert wire_mcp(_cursor_host(cfg))[0] is Status.FAILED


def test_install_list_runs() -> None:
    result = runner.invoke(app, ["install", "list"])
    assert result.exit_code == 0
    assert "cursor" in result.output


def test_install_unknown_host_errors() -> None:
    result = runner.invoke(app, ["install", "nope"])
    assert result.exit_code == 2

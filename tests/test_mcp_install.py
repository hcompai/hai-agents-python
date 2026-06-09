from __future__ import annotations

import json
import stat
import subprocess

from typer.testing import CliRunner

from hai_agents_cli import mcp_hosts
from hai_agents_cli.app import app
from hai_agents_cli.mcp_hosts import Client, Status, resolve_mcp_url, wire_mcp, wire_skill

runner = CliRunner()


def test_resolve_mcp_url_prefers_override_then_base_origin_then_eu() -> None:
    assert resolve_mcp_url(None, None) == mcp_hosts.DEFAULT_MCP_URL
    assert resolve_mcp_url(None, "https://x.test/mcp") == "https://x.test/mcp"
    assert resolve_mcp_url("https://agp.staging.sandboxh.ai/api/v2", None) == "https://agp.staging.sandboxh.ai/mcp"


def test_registry_leaves_carry_bearer_and_client_specific_url_key() -> None:
    rendered = {
        cid: mcp_hosts._render(c.leaf, "https://u/mcp", "hk-1") for cid, c in mcp_hosts.CLIENTS.items() if c.leaf
    }
    assert rendered["cursor"] == {"url": "https://u/mcp", "headers": {"Authorization": "Bearer hk-1"}}
    assert rendered["vscode"]["type"] == "http" and rendered["vscode"]["url"] == "https://u/mcp"
    assert rendered["windsurf"]["serverUrl"] == "https://u/mcp"


def test_wire_json_merges_preserves_and_is_idempotent(tmp_path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"url": "keep"}}}), encoding="utf-8")
    c = Client(
        name="X",
        config_path=str(path),
        key_path=("mcpServers", "hai-agents"),
        leaf={"url": mcp_hosts._URL, "headers": {"Authorization": f"Bearer {mcp_hosts._KEY}"}},
    )

    status, _ = wire_mcp(c, "https://u/mcp", "hk-secret")
    assert status is Status.INSTALLED
    data = json.loads(path.read_text())
    assert data["mcpServers"]["other"] == {"url": "keep"}
    assert data["mcpServers"]["hai-agents"] == {
        "url": "https://u/mcp",
        "headers": {"Authorization": "Bearer hk-secret"},
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    assert wire_mcp(c, "https://u/mcp", "hk-secret")[0] is Status.SKIPPED


def test_cli_install_removes_then_adds_at_user_scope(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(mcp_hosts.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, **_):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mcp_hosts.subprocess, "run", fake_run)

    status, _ = wire_mcp(mcp_hosts.CLIENTS["claude-code"], "https://u/mcp", "hk-rotated")

    assert status is Status.INSTALLED
    remove, add = calls
    assert remove[1:3] == ["mcp", "remove"] and remove[remove.index("--scope") + 1] == "user"
    assert add[1:3] == ["mcp", "add"] and add[add.index("--scope") + 1] == "user"
    assert "Authorization: Bearer hk-rotated" in add


def test_install_writes_detected_client_and_warns(monkeypatch, tmp_path) -> None:
    path = tmp_path / "mcp.json"
    monkeypatch.setitem(
        mcp_hosts.CLIENTS,
        "cursor",
        Client(
            name="Cursor",
            config_path=str(path),
            key_path=("mcpServers", "hai-agents"),
            leaf=mcp_hosts.CLIENTS["cursor"].leaf,
        ),
    )

    result = runner.invoke(app, ["mcp", "install", "cursor"], env={"HAI_API_KEY": "hk-test"})

    assert result.exit_code == 0, result.output
    assert "plaintext" in result.output
    assert json.loads(path.read_text())["mcpServers"]["hai-agents"]["headers"]["Authorization"] == "Bearer hk-test"


def test_install_requires_api_key(monkeypatch, tmp_path) -> None:
    from hai_agents_common import credentials

    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.delenv("H_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "LOCAL_ENV_PATH", tmp_path / "local.env")
    monkeypatch.setattr(credentials, "GLOBAL_ENV_PATH", tmp_path / "global.env")

    result = runner.invoke(app, ["mcp", "install", "cursor"], env={})

    assert result.exit_code != 0
    text = "\n".join(part for part in (result.output, result.stderr, str(result.exception)) if part)
    assert "No API key found" in text


def test_install_list_enumerates_clients() -> None:
    result = runner.invoke(app, ["mcp", "install", "list"])

    assert result.exit_code == 0
    assert "cursor" in result.output and "windsurf" in result.output


def test_wire_skill_symlinks_bundled_skill_and_is_idempotent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".cursor").mkdir()
    c = Client(name="X", skills_dir=".cursor/skills")

    assert wire_skill(c)[0] is Status.INSTALLED
    link = tmp_path / ".cursor" / "skills" / "hai-agents"
    assert link.is_symlink() and (link / "SKILL.md").exists()
    assert wire_skill(c)[0] is Status.SKIPPED


def test_wire_skill_absent_when_client_dir_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert wire_skill(Client(name="X", skills_dir=".cursor/skills"))[0] is Status.ABSENT

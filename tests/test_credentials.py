from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

import hai_agents.client as sdk_client
import hai_agents_cli.app as app_module
from hai_agents import AsyncClient, Client
from hai_agents.core.api_error import ApiError
from hai_agents_cli import auth
from hai_agents_cli.app import app
from hai_agents_common import credentials

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Point credential resolution at empty temp files and a clean environment."""
    for var in (credentials.API_KEY_VAR, credentials.BASE_URL_VAR, credentials.PORTAL_URL_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(credentials, "LOCAL_ENV_PATH", tmp_path / "local.env")
    monkeypatch.setattr(credentials, "GLOBAL_ENV_PATH", tmp_path / "global.env")
    monkeypatch.setattr(sdk_client, "CREDENTIALS_PATH", tmp_path / "global.env")


def test_env_var_beats_dotenv(monkeypatch):
    credentials.GLOBAL_ENV_PATH.write_text("HAI_API_KEY=hk-from-file\n")
    monkeypatch.setenv("HAI_API_KEY", "hk-from-env")

    assert credentials.resolve_api_key() == "hk-from-env"
    assert credentials.source() == "environment"


def test_local_dotenv_overrides_global():
    credentials.GLOBAL_ENV_PATH.write_text("HAI_API_KEY=hk-global\n")
    credentials.LOCAL_ENV_PATH.write_text("HAI_API_KEY=hk-local\n")

    assert credentials.resolve_api_key() == "hk-local"
    assert credentials.source() == str(credentials.LOCAL_ENV_PATH)


def test_missing_key_raises_with_guidance():
    with pytest.raises(RuntimeError, match="No API key found"):
        credentials.resolve_api_key()


def test_save_then_clear_roundtrip(monkeypatch):
    path = credentials.save_api_key("hk-minted")

    assert path == credentials.GLOBAL_ENV_PATH
    assert "hk-minted" in credentials.GLOBAL_ENV_PATH.read_text()

    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)  # forget the process-env write
    assert credentials.resolve_api_key() == "hk-minted"

    credentials.clear_api_key()
    with pytest.raises(RuntimeError):
        credentials.resolve_api_key()


def test_absolute_share_url_prepends_base():
    class _Wrapper:
        def get_base_url(self) -> str:
            return "https://agp.example.test/"

    class _Client:
        _client_wrapper = _Wrapper()

    assert credentials.absolute_share_url(_Client(), "/share/abc") == "https://agp.example.test/share/abc"
    assert credentials.absolute_share_url(_Client(), "https://x/y") == "https://x/y"


def test_login_requires_a_browser():
    result = runner.invoke(app, ["login"])

    assert result.exit_code != 0
    assert "interactive terminal" in _error_text(result)


def test_login_short_circuits_when_signed_in(monkeypatch):
    monkeypatch.setattr(app_module.credentials, "current_api_key", lambda *_: "hk-existing")

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0
    assert "Already signed in" in result.output


def test_login_portal_follows_the_platform_region(monkeypatch):
    assert credentials.portal_base() == "https://portal.api.eu.hcompany.ai"
    assert credentials.portal_base("https://agp.hcompany.ai/") == "https://portal.production.hcompany.ai"
    with pytest.raises(RuntimeError, match=credentials.PORTAL_URL_VAR):
        credentials.portal_base("https://agp.example.test")

    monkeypatch.setenv(credentials.PORTAL_URL_VAR, "https://portal.example.test")
    assert credentials.portal_base("https://agp.example.test") == "https://portal.example.test"


def test_portal_failure_shows_the_portal_reason():
    request = httpx.Request("POST", "https://portal.example.test/api/auth/desktop/exchange")
    response = httpx.Response(401, json={"title": "invalid_desktop_code", "detail": "User not found."}, request=request)

    with pytest.raises(auth.PortalError, match="returned 401: User not found"):
        auth._ok(response)


@pytest.mark.parametrize(("status", "saved"), [(None, True), (401, False)])
def test_login_key_validates_then_stores(monkeypatch, status, saved):
    class _Sessions:
        def get_session_quota(self):
            if status:
                raise ApiError(status_code=status, body={"detail": "Invalid API key"})

    monkeypatch.setattr(app_module, "make_client", lambda **_: type("C", (), {"sessions": _Sessions()})())

    result = runner.invoke(app, ["login", "--key"], input="hk-pasted\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    stored = credentials.GLOBAL_ENV_PATH.read_text() if credentials.GLOBAL_ENV_PATH.exists() else ""
    assert (result.exit_code == 0) is saved
    assert ("hk-pasted" in stored) is saved
    if not saved:
        assert "rejected this key" in _error_text(result)


@pytest.mark.parametrize("client_type", [Client, AsyncClient])
def test_sdk_client_falls_back_to_the_key_hai_login_stored(monkeypatch, client_type):
    with pytest.raises(ApiError, match="hai login"):
        client_type()

    credentials.save_api_key("hk-stored")
    monkeypatch.delenv(credentials.API_KEY_VAR)
    assert client_type()._client_wrapper._get_api_key() == "hk-stored"

    monkeypatch.setenv(credentials.API_KEY_VAR, "hk-env")
    assert client_type()._client_wrapper._get_api_key() == "hk-env"
    assert client_type(api_key="hk-arg")._client_wrapper._get_api_key() == "hk-arg"


def test_commands_sign_in_on_first_use_then_run(monkeypatch):
    listed = []
    fake = SimpleNamespace(
        sessions=SimpleNamespace(get_session_quota=lambda: None),
        agents=SimpleNamespace(list_agents=lambda **_: listed.append(True) or SimpleNamespace(items=[])),
    )
    monkeypatch.setattr(app_module, "make_client", lambda **_: fake)
    monkeypatch.setattr(app_module, "_interactive", lambda: True)

    result = runner.invoke(app, ["agents", "list"], input="2\nhk-pasted\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    assert result.exit_code == 0, _error_text(result)
    assert "hk-pasted" in credentials.GLOBAL_ENV_PATH.read_text()
    assert listed == [True]


@pytest.mark.parametrize(("args", "interactive"), [(["agents", "list"], False), (["--json", "agents", "list"], True)])
def test_scripts_never_get_a_sign_in_prompt(monkeypatch, args, interactive):
    monkeypatch.setattr(app_module, "_interactive", lambda: interactive)

    result = runner.invoke(app, args, input="2\nhk-pasted\n")

    assert result.exit_code == 1
    assert "No API key found" in _error_text(result)
    assert not credentials.GLOBAL_ENV_PATH.exists()


def _error_text(result) -> str:
    return "\n".join(part for part in (result.output, result.stderr, str(result.exception)) if part)


def test_login_key_is_a_no_op_when_a_key_is_already_stored(monkeypatch):
    """Pasted snippets start with `hai login --key`; a second paste must not ask again."""
    monkeypatch.setattr(app_module.credentials, "current_api_key", lambda *_: "hk-existing")
    monkeypatch.setattr(app_module, "make_client", lambda **_: pytest.fail("must not validate or store anything"))

    result = runner.invoke(app, ["login", "--key"], input="hk-pasted\n")

    assert result.exit_code == 0
    assert "Already signed in" in result.output


def test_login_key_force_replaces_a_stored_key(monkeypatch):
    class _Sessions:
        def get_session_quota(self):
            pass

    monkeypatch.setattr(app_module, "make_client", lambda **_: type("C", (), {"sessions": _Sessions()})())
    credentials.save_api_key("hk-existing")

    result = runner.invoke(app, ["login", "--key", "--force"], input="hk-new\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    assert result.exit_code == 0, _error_text(result)
    assert "hk-new" in credentials.GLOBAL_ENV_PATH.read_text()

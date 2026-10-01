from __future__ import annotations

import httpx
import pytest
from typer.testing import CliRunner

import hai_agents_cli.app as app_module
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
    monkeypatch.setattr(app_module.credentials, "current_api_key", lambda *_: "hk-existing")

    result = runner.invoke(app, ["login", "--key"], input="hk-pasted\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    stored = credentials.GLOBAL_ENV_PATH.read_text() if credentials.GLOBAL_ENV_PATH.exists() else ""
    assert (result.exit_code == 0) is saved
    assert ("hk-pasted" in stored) is saved
    if not saved:
        assert "rejected this key" in _error_text(result)


def _error_text(result) -> str:
    return "\n".join(part for part in (result.output, result.stderr, str(result.exception)) if part)


def test_browser_sign_in_lets_the_platform_pick_the_method(monkeypatch):
    """No provider hint: the portal sends the browser to the platform login page, where every method works."""
    opened: list[str] = []
    monkeypatch.setattr(auth.webbrowser, "open", lambda url: opened.append(url))

    def _abort(redirect_uri, *args):
        raise RuntimeError("stop before serving the loopback")

    monkeypatch.setattr(auth, "_await_code", _abort)
    with pytest.raises(RuntimeError, match="stop before"):
        auth.login_and_mint("https://portal.test", "lbl", lambda url: None)

    assert len(opened) == 1
    query = httpx.URL(opened[0]).params
    assert httpx.URL(opened[0]).path == "/api/auth/authorize"
    assert "provider" not in query
    assert query["code_challenge_method"] == "S256" and query["redirect_uri"].startswith("http://127.0.0.1:")


def test_minting_names_the_identity_and_revokes_the_web_session():
    calls: list = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={"user": {"email": "me@example.com"}, "org_id": "org-1"})
        if request.url.path == "/api/organizations/":
            return httpx.Response(200, json=[{"id": "org-1", "name": "Acme"}])
        if request.url.path == "/api/organizations/org-1/keys/":
            return httpx.Response(200, json={"id": "k1", "key": "hk-minted"})
        if request.url.path == "/api/auth/sessions/web-session":
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": "unexpected"})

    with httpx.Client(transport=httpx.MockTransport(handle), headers={"Authorization": "Bearer jwt"}) as client:
        signed_in = auth._mint_for_signed_in_user(client, "https://portal.test", "lbl", session_id="web-session")

    assert signed_in == auth.SignedIn(key="hk-minted", email="me@example.com", organization="Acme")
    assert ("DELETE", "/api/auth/sessions/web-session") in calls
    assert calls.index(("POST", "/api/organizations/org-1/keys/")) < calls.index(
        ("DELETE", "/api/auth/sessions/web-session")
    )


def test_minting_survives_a_failed_session_revoke():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={"email": "me@example.com", "org_id": "org-1"})
        if request.url.path == "/api/organizations/org-1/keys/":
            return httpx.Response(200, json={"id": "k1", "key": "hk-minted"})
        if request.url.path == "/api/organizations/":
            return httpx.Response(404, json={"detail": "nope"})
        raise httpx.ConnectError("portal gone")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        signed_in = auth._mint_for_signed_in_user(client, "https://portal.test", "lbl", session_id="s")

    assert signed_in.key == "hk-minted" and signed_in.organization is None


def test_identity_line_never_shows_an_org_id(monkeypatch):
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(
        app_module.auth, "login_and_mint", lambda *a, **k: auth.SignedIn("hk-x", "me@example.com", None)
    )

    result = runner.invoke(app, ["login"])
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    assert result.exit_code == 0, _error_text(result)
    assert "Signed in as me@example.com." in result.output
    assert "organization" not in result.output

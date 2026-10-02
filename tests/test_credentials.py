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


def _portal_transport(calls: list, *, mfa: bool = False, wrong_password: bool = False) -> httpx.MockTransport:
    """A fake portal: token (+ MFA) login, /me, and key minting. Records every request."""

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("X-SDK-Auth"), request.content))
        if request.url.path == "/api/auth/token":
            if wrong_password:
                return httpx.Response(
                    401, json={"title": "not_authorized", "detail": "Incorrect username or password."}
                )
            if mfa:
                return httpx.Response(
                    200, json={"success": True, "mfa_required": True, "message": "MFA challenge required"}
                )
            return httpx.Response(
                200, json={"success": True, "access_token": "jwt-plain", "refresh_token": "r", "session_id": "s"}
            )
        if request.url.path == "/api/auth/token-mfa":
            return httpx.Response(200, json={"success": True, "staging_access_token": "jwt-mfa"})
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={"user": {"email": "me@example.com"}, "org_id": "org-1"})
        if request.url.path == "/api/organizations/":
            return httpx.Response(200, json=[{"id": "org-1", "name": "Acme"}])
        if request.method == "DELETE" and request.url.path.startswith("/api/auth/sessions/"):
            return httpx.Response(204)
        if request.url.path == "/api/organizations/org-1/keys/":
            return httpx.Response(
                200, json={"id": "k1", "key": "hk-minted-" + request.headers["Authorization"].split()[1]}
            )
        return httpx.Response(404, json={"detail": "unexpected"})

    return httpx.MockTransport(handle)


def test_password_login_mints_a_key_in_sdk_mode():
    calls: list = []

    signed_in = auth.login_with_password(
        "https://portal.test",
        "lbl",
        " me@example.com ",
        "pw",
        ask_code=lambda: "000000",
        transport=_portal_transport(calls),
    )

    assert signed_in == auth.SignedIn(key="hk-minted-jwt-plain", email="me@example.com", organization="Acme")
    method, path, sdk_header, body = calls[0]
    assert (method, path, sdk_header) == ("POST", "/api/auth/token", "true")
    assert b'"email":"me@example.com"' in body  # trimmed
    assert [c[1] for c in calls] == [
        "/api/auth/token",
        "/api/auth/me",
        "/api/organizations/org-1/keys/",
        "/api/organizations/",
        "/api/auth/sessions/s",  # the web session is revoked once the key exists
    ]


def test_password_login_answers_the_mfa_challenge():
    calls: list = []
    asked = []

    def ask_code() -> str:
        asked.append(True)
        return " 123456 "

    signed_in = auth.login_with_password(
        "https://portal.test",
        "lbl",
        "me@example.com",
        "pw",
        ask_code=ask_code,
        transport=_portal_transport(calls, mfa=True),
    )

    assert signed_in.key == "hk-minted-jwt-mfa"  # the env-prefixed token key is still found
    assert asked == [True]
    assert calls[1][1] == "/api/auth/token-mfa" and b'"code":"123456"' in calls[1][3]


def test_password_login_surfaces_the_portal_reason():
    with pytest.raises(auth.PortalError, match="Incorrect username or password"):
        auth.login_with_password(
            "https://portal.test",
            "lbl",
            "me@example.com",
            "nope",
            ask_code=lambda: "",
            transport=_portal_transport([], wrong_password=True),
        )


def test_login_email_option_goes_straight_to_the_password_prompt(monkeypatch):
    seen = {}

    def _fake(portal, label, email, password, ask_code):
        seen.update(email=email, password=password)
        return auth.SignedIn("hk-from-password", "me@example.com", "Acme")

    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(app_module.auth, "login_with_password", _fake)

    result = runner.invoke(app, ["login", "--email", "me@example.com"], input="s3cret\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    assert result.exit_code == 0, _error_text(result)
    assert seen == {"email": "me@example.com", "password": "s3cret"}
    assert "hk-from-password" in credentials.GLOBAL_ENV_PATH.read_text()
    assert "me@example.com" in result.output and "Acme" in result.output


def test_login_asks_the_method_and_takes_email_and_password(monkeypatch):
    seen = {}
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(
        app_module.auth,
        "login_with_password",
        lambda p, l, email, password, ask_code: seen.update(email=email) or auth.SignedIn("hk-x", email, "Acme"),
    )
    monkeypatch.setattr(app_module.auth, "login_and_mint", lambda *a, **k: pytest.fail("browser flow must not run"))

    result = runner.invoke(app, ["login"], input="2\nme@example.com\npw\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    assert result.exit_code == 0, _error_text(result)
    assert "Email and password" in result.output
    assert seen == {"email": "me@example.com"}


def test_login_default_choice_is_the_browser(monkeypatch):
    monkeypatch.setattr(app_module, "_interactive", lambda: True)
    monkeypatch.setattr(
        app_module.auth, "login_and_mint", lambda *a, **k: auth.SignedIn("hk-from-browser", "me@example.com", "Acme")
    )
    monkeypatch.setattr(
        app_module.auth, "login_with_password", lambda *a, **k: pytest.fail("password flow must not run")
    )

    result = runner.invoke(app, ["login"], input="\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    assert result.exit_code == 0, _error_text(result)
    assert "hk-from-browser" in credentials.GLOBAL_ENV_PATH.read_text()


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
    assert calls.index(("POST", "/api/organizations/org-1/keys/")) < calls.index(
        ("DELETE", "/api/auth/sessions/web-session")
    )


def test_minting_survives_a_failed_session_revoke_and_unreadable_org_list():
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
    monkeypatch.setattr(app_module.auth, "login_with_password", lambda *a, **k: pytest.fail("not this flow"))

    result = runner.invoke(app, ["login"], input="\n")
    monkeypatch.delenv(credentials.API_KEY_VAR, raising=False)

    assert result.exit_code == 0, _error_text(result)
    assert "Signed in as me@example.com." in result.output
    assert "organization" not in result.output.split("Signed in as")[1]

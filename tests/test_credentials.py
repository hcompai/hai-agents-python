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
    monkeypatch.setattr(app_module, "_key_file_notices_shown", set())  # the once-per-process memo


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


def _private(path, content):
    path.write_text(content)
    path.chmod(0o600)


def test_project_env_is_used_with_a_warning_once(monkeypatch):
    credentials.LOCAL_ENV_PATH.write_text("HAI_API_KEY=hk-local\n")  # umask mode, like any checked-out file

    result = runner.invoke(app, ["whoami"])

    assert result.exit_code == 0, _error_text(result)
    text = result.output.replace("\n", "")  # output already interleaves stderr; count there only
    assert text.count("Make sure this key is yours") == 1
    assert "someone else's key" in text and "hk-local" not in text


def test_no_warning_for_the_environment_variable_or_the_global_file(monkeypatch):
    _private(credentials.GLOBAL_ENV_PATH, "HAI_API_KEY=hk-global\n")
    assert "Make sure this key is yours" not in _unwrapped(runner.invoke(app, ["whoami"]))

    monkeypatch.setenv("HAI_API_KEY", "hk-env")
    assert "Make sure this key is yours" not in _unwrapped(runner.invoke(app, ["whoami"]))


def test_unrelated_project_env_is_left_alone():
    _private(credentials.GLOBAL_ENV_PATH, "HAI_API_KEY=hk-global\n")
    credentials.LOCAL_ENV_PATH.write_text("DATABASE_URL=postgres://x\nFOO=bar\n")

    assert credentials.resolve_api_key() == "hk-global"
    assert credentials.key_file_warnings() == []
    assert "Make sure" not in _unwrapped(runner.invoke(app, ["whoami"]))


def test_world_readable_global_file_is_ignored():
    """`hai login` writes the global file 0600; anything looser is not ours to trust."""
    credentials.GLOBAL_ENV_PATH.write_text("HAI_API_KEY=hk-global\n")
    credentials.GLOBAL_ENV_PATH.chmod(0o644)

    with pytest.raises(RuntimeError, match="No API key found"):
        credentials.resolve_api_key()
    assert credentials.key_file_warnings() == [
        f"Ignoring {credentials.GLOBAL_ENV_PATH}: readable by others; run `chmod 600` on it"
    ]


def test_symlinked_project_env_is_ignored(tmp_path):
    target = tmp_path / "elsewhere.env"
    target.write_text("HAI_API_KEY=hk-elsewhere\n")
    credentials.LOCAL_ENV_PATH.symlink_to(target)

    with pytest.raises(RuntimeError, match="No API key found"):
        credentials.resolve_api_key()
    assert "not a regular file" in credentials.key_file_warnings()[0]


def test_doctor_repeats_the_warning_for_a_project_key():
    from hai_agents_cli import doctor

    credentials.LOCAL_ENV_PATH.write_text("HAI_API_KEY=hk-local\n")

    check = doctor.check_login(None)

    assert check.ok is True and "Make sure this key is yours" in check.detail


def _unwrapped(result) -> str:
    """Console text with Rich's soft line wraps undone, for matching long sentences."""
    return _error_text(result).replace("\n", "")


def test_every_command_warns_about_a_project_key_even_in_json_mode():
    credentials.LOCAL_ENV_PATH.write_text("HAI_API_KEY=hk-local\n")

    result = runner.invoke(app, ["--json", "whoami"])

    assert result.exit_code == 0, _error_text(result)
    assert "Make sure this key is yours" in _unwrapped(result)
    assert "hk-local" not in _error_text(result)


def test_a_binary_project_env_is_ignored_instead_of_crashing():
    credentials.LOCAL_ENV_PATH.write_bytes(b"\xff\xfe\x00not text\x00")

    result = runner.invoke(app, ["whoami"], env={"HAI_API_KEY": "hk-env"})

    assert result.exit_code == 0, _error_text(result)
    assert credentials.key_file_warnings() == []


def test_a_symlinked_project_env_is_never_read(monkeypatch, tmp_path):
    """The shortcut check runs before the content check, so a link to /dev/zero cannot hang the CLI."""
    target = tmp_path / "elsewhere.env"
    target.write_text("HAI_API_KEY=hk-elsewhere\n")
    credentials.LOCAL_ENV_PATH.symlink_to(target)
    monkeypatch.setattr(credentials, "dotenv_values", lambda *_: pytest.fail("the symlink must not be read"))

    assert credentials.key_file_warnings() == [f"Ignoring {credentials.LOCAL_ENV_PATH}: not a regular file (symlink?)"]
    assert credentials.current_api_key() is None


def test_a_dangling_symlink_is_reported():
    credentials.LOCAL_ENV_PATH.symlink_to(credentials.LOCAL_ENV_PATH.parent / "missing.env")

    assert "not a regular file" in credentials.key_file_warnings()[0]

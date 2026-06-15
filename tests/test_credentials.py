from __future__ import annotations

import pytest
from typer.testing import CliRunner

import hai_agents_cli.app as app_module
from hai_agents_cli.app import app
from hai_agents_common import credentials

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Point credential resolution at empty temp files and a clean environment."""
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.delenv("H_API_KEY", raising=False)
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


def test_canonical_key_beats_legacy_alias(monkeypatch):
    monkeypatch.setenv("H_API_KEY", "hk-legacy")
    monkeypatch.setenv("HAI_API_KEY", "hk-canonical")

    assert credentials.resolve_api_key() == "hk-canonical"


def test_legacy_h_api_key_still_accepted(monkeypatch):
    monkeypatch.setenv("H_API_KEY", "hk-legacy")

    assert credentials.resolve_api_key() == "hk-legacy"


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


def _error_text(result) -> str:
    return "\n".join(part for part in (result.output, result.stderr, str(result.exception)) if part)

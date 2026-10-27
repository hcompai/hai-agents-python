import pytest

from hai_agents_cli import holo_dir, welcome
from hai_agents_local import desktop_lock
from hai_agents_local.config import AUTO_BRIDGE_ENV_VAR


@pytest.fixture(autouse=True)
def _no_auto_bridges(monkeypatch):
    monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "0")


@pytest.fixture(autouse=True)
def _isolated_desktop_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop_lock, "LOCK_PATH", tmp_path / "desktop.lock")


@pytest.fixture(autouse=True)
def holo_home(monkeypatch, tmp_path):
    monkeypatch.setattr(holo_dir, "HOLO_DIR", tmp_path / "holo")
    return tmp_path / "holo"


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    monkeypatch.setattr(welcome, "latest_version", lambda: None)

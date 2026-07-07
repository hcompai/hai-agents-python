import pytest

from hai_agents.local.config import AUTO_BRIDGE_ENV_VAR


@pytest.fixture(autouse=True)
def _no_auto_bridges(monkeypatch):
    monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "0")

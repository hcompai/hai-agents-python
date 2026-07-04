"""Client.local wiring: base_url/api_key come from the LocalRuntime, imported lazily."""

from __future__ import annotations

import os
import sys

import pytest

from hai_agents import AsyncClient, Client
from tests.conftest import free_port

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="local-mode tests exercise POSIX process groups and file modes"
)


class _StubRuntime:
    base_url = "http://127.0.0.1:18795"
    api_key = "local-token-abc"


def test_client_local_wires_runtime_url_and_bearer() -> None:
    client = Client.local(runtime=_StubRuntime())

    assert client._client_wrapper.get_base_url() == "http://127.0.0.1:18795"
    assert client._client_wrapper.get_headers()["Authorization"] == "Bearer local-token-abc"


def test_client_local_never_uses_the_cloud_env_key_as_bearer(monkeypatch) -> None:
    monkeypatch.setenv("HAI_API_KEY", "hk-cloud")

    client = Client.local(runtime=_StubRuntime())

    assert client._client_wrapper.get_headers()["Authorization"] == "Bearer local-token-abc"


def test_async_client_local_wires_the_same_runtime() -> None:
    client = AsyncClient.local(runtime=_StubRuntime())

    assert client._client_wrapper.get_base_url() == "http://127.0.0.1:18795"
    assert client._client_wrapper.get_headers()["Authorization"] == "Bearer local-token-abc"


def test_client_local_raises_a_helpful_import_error(monkeypatch) -> None:
    # Simulate a broken/missing hai_agents.local: a None entry makes `import` raise ImportError.
    for name in [m for m in sys.modules if m == "hai_agents.local" or m.startswith("hai_agents.local.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "hai_agents.local", None)

    with pytest.raises(ImportError, match=r'pip install "hai-agents\[local\]"'):
        Client.local()


def test_client_local_end_to_end_against_fake_runtime(fake_binary, tmp_path) -> None:
    port = free_port()
    client = Client.local(binary_path=fake_binary, cache_dir=tmp_path / "cache", port=port, timeout_s=20.0)
    runtime = client._local_runtime
    try:
        # The generated sessions client works unchanged against the local endpoint,
        # authenticated with the generated bearer (the fake 401s any other token).
        page = client.sessions.list_sessions(size=1)
        assert page.items == []
        assert runtime.owned is True
    finally:
        runtime.shutdown()

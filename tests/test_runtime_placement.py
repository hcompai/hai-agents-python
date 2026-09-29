"""Placement boundaries: authentication, compatibility and executor ownership."""

import httpx
import pytest

from hai_agents import AsyncClient, Client, Inference
from hai_agents.local.errors import BinaryIncompatibleError, LocalRuntimeError
from hai_agents.local.runtime import LocalRuntime
from hai_agents.local.state import token_file_path, write_owner_only
from hai_agents.sessions.client import AsyncSessionsClient, SessionsClient


def test_both_clients_respect_product_owned_execution():
    assert type(Client(api_key="test", auto_bridges=False).sessions) is SessionsClient
    assert type(AsyncClient(api_key="test", auto_bridges=False).sessions) is AsyncSessionsClient


def test_self_hosted_inference_does_not_receive_hosted_key(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "hosted-secret")
    env = Inference.self_hosted("http://127.0.0.1:8000/v1", model="my-model").runtime_env()
    assert "HAI_API_KEY" not in env
    assert env["HAI_AGENT_RUNTIME_MODEL"] == "my-model"
    monkeypatch.setenv("HAI_AGENT_RUNTIME_BASE_URL", "http://localhost:8000/v1")
    assert "HAI_AGENT_RUNTIME_BASE_URL" not in Inference.cloud().runtime_env()


def test_attachment_authenticates_and_checks_recipe_before_use(tmp_path, monkeypatch):
    from hai_agents.local import runtime as module

    write_owner_only(token_file_path(18795, cache_dir=tmp_path), "local-token")
    monkeypatch.delenv("HAI_AGENT_RUNTIME_API_TOKEN", raising=False)
    monkeypatch.setattr(module, "probe_health", lambda url: {"version": "old", "recipe": "desktop"})
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["headers"])
        return httpx.Response(200)

    monkeypatch.setattr(module.httpx, "get", get)
    attached = LocalRuntime.attach(cache_dir=tmp_path)
    assert calls == [{"Authorization": "Bearer local-token"}]
    with pytest.raises(BinaryIncompatibleError):
        attached.require_recipe("shared")
    with pytest.raises(LocalRuntimeError):
        attached.force_kill()
    assert token_file_path(18795, cache_dir=tmp_path).exists()
    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: httpx.Response(401))
    with pytest.raises(LocalRuntimeError, match="authenticated"):
        LocalRuntime.attach(cache_dir=tmp_path)


@pytest.mark.parametrize("url", ["https://remote.example", "http://user:pass@localhost:80"])
def test_local_attach_rejects_remote_or_credential_urls(tmp_path, monkeypatch, url):
    monkeypatch.setenv("HAI_AGENT_LOCAL_BASE_URL", url)
    with pytest.raises(LocalRuntimeError, match="loopback"):
        LocalRuntime.attach(cache_dir=tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("borrowed", [False, True])
async def test_client_close_releases_only_owned_runtime_and_http(monkeypatch, asynchronous, borrowed):
    class Runtime:
        base_url = "http://127.0.0.1:18795"
        api_key = "local-token"
        owned = True
        stopped = False

        def require_recipe(self, recipe):
            assert recipe == "shared"

        def shutdown(self):
            self.stopped = True

    runtime = Runtime()
    monkeypatch.setattr(LocalRuntime, "ensure_started", lambda **options: runtime)
    http = httpx.AsyncClient() if asynchronous else httpx.Client()
    client_type = AsyncClient if asynchronous else Client
    options = {"runtime": runtime, "httpx_client": http} if borrowed else {}
    client = client_type(mode="local", **options)
    if asynchronous:
        await client.aclose()
    else:
        client.close()
    assert runtime.stopped is (not borrowed)
    if borrowed:
        assert not http.is_closed
    if asynchronous:
        await http.aclose()
    else:
        http.close()

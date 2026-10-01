"""Placement boundaries: authentication, compatibility and executor ownership."""

import httpx
import pytest

from hai_agents import AsyncClient, Client
from hai_agents_local.runtime import BinaryIncompatibleError, Inference, LocalRuntime, LocalRuntimeError
from hai_agents_local.runtime.state import token_file_path, write_owner_only


class FakeRuntime:
    base_url = "http://127.0.0.1:18795"
    api_key = "local-token"
    owned = True

    def __init__(self):
        self.stopped = False

    def require_recipe(self, recipe):
        assert recipe == "shared"

    def http_client(self, timeout=None):
        return httpx.Client()

    def async_http_client(self, timeout=None):
        return httpx.AsyncClient()

    def shutdown(self):
        self.stopped = True


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_local_client_without_auto_bridges_leaves_execution_to_the_product(monkeypatch, asynchronous):
    from hai_agents.sessions.client import AsyncSessionsClient, SessionsClient

    monkeypatch.setenv("HAI_AUTO_BRIDGE", "1")
    served = []
    monkeypatch.setattr("hai_agents_local.sessions.ensure_bridges", lambda bridges: served.extend(bridges) or [])
    requested = []

    def create(self, **kwargs):
        requested.append(kwargs)
        return type("Session", (), {"id": "run"})()

    async def async_create(self, **kwargs):
        return create(self, **kwargs)

    monkeypatch.setattr(SessionsClient, "create_session", create)
    monkeypatch.setattr(AsyncSessionsClient, "create_session", async_create)
    agent = {"name": "qa", "environments": [{"id": "desktop", "kind": "desktop", "host": "user_device"}]}
    if asynchronous:
        async with await AsyncClient.local(runtime=FakeRuntime(), auto_bridges=False) as client:
            await client.sessions.create_session(agent=agent, messages="test")
    else:
        with Client.local(runtime=FakeRuntime(), auto_bridges=False) as client:
            client.sessions.create_session(agent=agent, messages="test")
    assert served == []
    assert requested[0]["agent"] == agent


def test_self_hosted_inference_does_not_receive_hosted_key(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "hosted-secret")
    env = Inference.self_hosted("http://127.0.0.1:8000/v1", model="my-model").runtime_env()
    assert "HAI_API_KEY" not in env
    assert env["HAI_AGENT_RUNTIME_MODEL"] == "my-model"
    monkeypatch.setenv("HAI_AGENT_RUNTIME_BASE_URL", "http://localhost:8000/v1")
    assert "HAI_AGENT_RUNTIME_BASE_URL" not in Inference.cloud().runtime_env()


@pytest.mark.parametrize("probe_error", [None, httpx.ConnectError("offline"), httpx.ReadTimeout("timeout")])
def test_attachment_authenticates_and_checks_recipe_before_use(tmp_path, monkeypatch, probe_error):
    from hai_agents_local.runtime import runtime as module

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

    def failed_probe(*args, **kwargs):
        if probe_error is not None:
            raise probe_error
        return httpx.Response(401)

    monkeypatch.setattr(module.httpx, "get", failed_probe)
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
async def test_client_close_releases_only_owned_runtime(monkeypatch, asynchronous, borrowed):
    runtime = FakeRuntime()
    monkeypatch.setattr(LocalRuntime, "ensure_started", lambda **options: runtime)
    options = {"runtime": runtime} if borrowed else {}
    if asynchronous:
        client = await AsyncClient.local(**options)
        await client.aclose()
    else:
        client = Client.local(**options)
        client.close()
    assert runtime.stopped is (not borrowed)
    assert client._client_wrapper.httpx_client.httpx_client.is_closed


def test_binary_resolution_does_not_hold_the_port_startup_lock(tmp_path, monkeypatch):
    from hai_agents_local.runtime import BinaryNotFoundError
    from hai_agents_local.runtime import runtime as module

    monkeypatch.delenv("HAI_AGENT_LOCAL_BASE_URL", raising=False)
    monkeypatch.setattr(LocalRuntime, "_attach", lambda **kwargs: None)

    def resolve(**kwargs):
        # A competing client can acquire this actual lock while resolution/download is pending.
        with module._startup_lock(tmp_path, 18795, 0.1):
            raise BinaryNotFoundError("candidate not installed")

    monkeypatch.setattr(LocalRuntime, "_resolve_command", resolve)
    with pytest.raises(BinaryNotFoundError, match="candidate not installed"):
        LocalRuntime.ensure_started(cache_dir=tmp_path, port=18795)


@pytest.mark.parametrize("status", [200, 400])
def test_idle_probe_uses_runtime_http_and_closes_its_pool(tmp_path, monkeypatch, status):
    from hai_agents.core.api_error import ApiError

    clients, requests, stopped = [], [], []
    original_client = httpx.Client

    def respond(request):
        requests.append(request)
        assert request.url.path == "/api/v2/sessions"
        assert request.headers["Authorization"] == "Bearer local-token"
        return httpx.Response(status, json={"items": [], "total": 0, "page": 1, "size": 1})

    def http_client(**kwargs):
        client = original_client(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", http_client)
    runtime = LocalRuntime(
        base_url="http://127.0.0.1:18795",
        api_key="local-token",
        pid=123,
        version=None,
        log_path=None,
        owned=True,
        cache_dir=tmp_path,
        port=18795,
    )
    monkeypatch.setattr(runtime, "shutdown", lambda: stopped.append(True))
    if status == 200:
        assert runtime.shutdown_if_idle()
        assert stopped == [True]
    else:
        with pytest.raises(ApiError):
            runtime.shutdown_if_idle()
        assert stopped == []
    assert requests
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
async def test_async_local_startup_keeps_loop_responsive_and_cancellation_cleans_child(monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace

    entered, release = threading.Event(), threading.Event()
    stopped = []
    runtime = SimpleNamespace(owned=True, shutdown=lambda: stopped.append(True))

    def start(**kwargs):
        entered.set()
        assert release.wait(5)
        return runtime

    monkeypatch.setattr(LocalRuntime, "ensure_started", start)
    startup = asyncio.create_task(AsyncClient.local())
    try:
        assert await asyncio.to_thread(entered.wait, 1), "startup blocked the event loop"
        startup.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await startup
        assert stopped == [True]
    finally:
        release.set()
        if not startup.done():
            await startup


def test_state_cleanup_waits_for_startup_and_preserves_replacement(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from hai_agents_local.runtime import runtime as module

    token_file = write_owner_only(token_file_path(18795, cache_dir=tmp_path), "old-token")
    runtime = LocalRuntime(
        base_url="http://127.0.0.1:18795",
        api_key="old-token",
        pid=123,
        version=None,
        log_path=None,
        owned=True,
        cache_dir=tmp_path,
        port=18795,
        token_file=token_file,
    )
    entered = threading.Event()

    def cleanup():
        entered.set()
        runtime._cleanup_state_files()

    with ThreadPoolExecutor() as pool:
        with module._startup_lock(tmp_path, 18795, 1):
            cleaning = pool.submit(cleanup)
            assert entered.wait(1)
            with pytest.raises(TimeoutError):
                cleaning.result(timeout=0.05)
            write_owner_only(token_file, "replacement-token")
        cleaning.result(timeout=2)
    assert token_file.read_text() == "replacement-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_attached_runtime_with_another_recipe_is_rejected_and_left_running(asynchronous):
    class Runtime(FakeRuntime):
        def require_recipe(self, recipe):
            raise BinaryIncompatibleError("recipe changed")

    runtime = Runtime()
    with pytest.raises(BinaryIncompatibleError, match="recipe changed"):
        if asynchronous:
            await AsyncClient.local(runtime=runtime)
        else:
            Client.local(runtime=runtime)
    assert not runtime.stopped

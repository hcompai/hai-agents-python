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


@pytest.mark.parametrize("probe_error", [None, httpx.ConnectError("offline"), httpx.ReadTimeout("timeout")])
def test_attachment_authenticates_and_checks_recipe_before_use(tmp_path, monkeypatch, probe_error):
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
    client = await AsyncClient.local() if asynchronous and not borrowed else client_type(mode="local", **options)
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


def test_binary_resolution_does_not_hold_the_port_startup_lock(tmp_path, monkeypatch):
    from hai_agents.local import runtime as module
    from hai_agents.local.errors import BinaryNotFoundError

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

    from hai_agents.local import runtime as module

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
@pytest.mark.parametrize("borrowed", [False, True])
async def test_failed_client_recipe_check_releases_only_started_runtime(monkeypatch, asynchronous, borrowed):
    stopped = []

    class Runtime:
        owned = True

        def require_recipe(self, recipe):
            raise BinaryIncompatibleError("recipe changed")

        def shutdown(self):
            stopped.append(True)

    runtime = Runtime()
    monkeypatch.setattr(LocalRuntime, "ensure_started", lambda **options: runtime)
    with pytest.raises(BinaryIncompatibleError, match="recipe changed"):
        if asynchronous and not borrowed:
            await AsyncClient.local()
        else:
            client_type = AsyncClient if asynchronous else Client
            client_type(mode="local", **({"runtime": runtime} if borrowed else {}))
    assert stopped == ([] if borrowed else [True])

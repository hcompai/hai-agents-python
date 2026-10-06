"""Placement boundaries: authentication, compatibility and executor ownership."""

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest

from hai_agents import AsyncClient, Client
from hai_agents_local.runtime import BinaryIncompatibleError, Inference, LocalRuntime, LocalRuntimeError
from hai_agents_local.runtime.state import token_file_path, write_owner_only


class RuntimeServer(ThreadingHTTPServer):
    """A loopback stand-in for the runtime: answers every response with an HMAC proof keyed by `proof_token`."""

    def __init__(self, token):
        super().__init__(("127.0.0.1", 0), _RuntimeHandler)
        self.token = token
        self.proof_token = token
        self.requests = []
        self.active = []
        self.cancelled = []

    @property
    def port(self):
        return self.server_address[1]


class _RuntimeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self._route()

    def do_DELETE(self):
        self._route()

    def _route(self):
        server = self.server
        server.requests.append({name.lower() for name in self.headers})
        path = urlsplit(self.path).path
        if path == "/health":
            return self._reply(200, {"recipe": "shared", "version": "test"})
        if self.headers.get("Authorization") != f"Bearer {server.token}":
            return self._reply(401, {"error": "unauthorized"})
        if self.command == "GET" and path == "/api/v2/sessions":
            items = [{"id": sid, "status": "running", "created_at": "2026-01-01T00:00:00Z"} for sid in server.active]
            return self._reply(200, {"items": items, "total": len(items), "page": 1})
        if self.command == "DELETE" and path.startswith("/api/v2/sessions/"):
            session_id = path.rsplit("/", 1)[1]
            server.cancelled.append(session_id)
            if session_id not in server.active:
                return self._reply(404, {"detail": "Session not found"})
            server.active.remove(session_id)
            return self._reply(204, None)
        self._reply(404, {"detail": "Not Found"})

    def _reply(self, status, body):
        payload = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        challenge = self.headers.get("X-Hai-Runtime-Challenge")
        if challenge and self.server.proof_token:
            proof = hmac.new(self.server.proof_token.encode(), challenge.encode(), hashlib.sha256).hexdigest()
            self.send_header("X-Hai-Runtime-Proof", proof)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def runtime_server(monkeypatch):
    monkeypatch.delenv("HAI_AGENT_RUNTIME_API_TOKEN", raising=False)
    monkeypatch.delenv("HAI_AGENT_LOCAL_BASE_URL", raising=False)
    server = RuntimeServer("local-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


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


def _owned_runtime(server, cache_dir, monkeypatch, stopped):
    runtime = LocalRuntime(
        base_url=f"http://127.0.0.1:{server.port}",
        api_key=server.token,
        pid=123,
        version=None,
        log_path=None,
        owned=True,
        cache_dir=cache_dir,
        port=server.port,
    )
    monkeypatch.setattr(runtime, "shutdown", lambda: stopped.append(True))
    return runtime


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


@pytest.mark.parametrize(
    ("inference", "forwarded"),
    [(None, "hk-stored"), (Inference.self_hosted("http://127.0.0.1:8000/v1", model="my-model"), None)],
)
def test_spawned_runtime_infers_with_the_key_hai_login_stored(tmp_path, monkeypatch, inference, forwarded):
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "hai").mkdir()
    (tmp_path / "hai" / ".env").write_text("HAI_API_KEY=hk-stored\n")
    launches = []

    def start(**options):
        launches.append(options)
        return FakeRuntime()

    monkeypatch.setattr(LocalRuntime, "ensure_started", start)
    Client.local(inference=inference, auto_bridges=False)
    assert launches[0]["spawn_env"].get("HAI_API_KEY") == forwarded


@pytest.mark.parametrize("proof_token", ["local-token", "squatter-token", None])
def test_only_the_runtime_holding_the_token_ever_receives_it(tmp_path, runtime_server, proof_token):
    write_owner_only(token_file_path(runtime_server.port, cache_dir=tmp_path), "local-token")
    runtime_server.proof_token = proof_token
    if proof_token != "local-token":
        with pytest.raises(LocalRuntimeError, match="did not prove"):
            LocalRuntime.attach(port=runtime_server.port, cache_dir=tmp_path)
        assert runtime_server.requests and not any("authorization" in seen for seen in runtime_server.requests)
        return
    attached = LocalRuntime.attach(port=runtime_server.port, cache_dir=tmp_path)
    with pytest.raises(BinaryIncompatibleError):
        attached.require_recipe("desktop")
    with pytest.raises(LocalRuntimeError):
        attached.shutdown()
    with Client.local(runtime=attached) as client:
        assert client.sessions.list_sessions().items == []
        runtime_server.proof_token = "squatter-token"
        with pytest.raises(LocalRuntimeError, match="did not prove"):
            client.sessions.list_sessions()


@pytest.mark.asyncio
async def test_bridge_never_serves_an_unproven_runtime(monkeypatch, runtime_server):
    from types import SimpleNamespace

    from hai_agents_local.sessions import _localize

    monkeypatch.delenv("HAI_AUTO_BRIDGE", raising=False)
    runtime_server.proof_token = "squatter-token"
    runtime = SimpleNamespace(api_key="local-token", base_url=f"http://127.0.0.1:{runtime_server.port}")
    agent = {"environments": [{"id": "workstation", "kind": "workstation", "host": "user_device"}]}
    [bridge] = _localize(None, runtime, {"agent": agent})
    bridge.create_driver = lambda: pytest.fail("a driver started for an unproven runtime")
    with pytest.raises(LocalRuntimeError, match="did not prove"):
        await bridge.run()


@pytest.mark.parametrize("url", ["https://remote.example", "http://user:pass@localhost:80"])
def test_local_attach_rejects_remote_or_credential_urls(tmp_path, monkeypatch, url):
    monkeypatch.setenv("HAI_AGENT_LOCAL_BASE_URL", url)
    with pytest.raises(LocalRuntimeError, match="loopback"):
        LocalRuntime.attach(cache_dir=tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("runtime_use", ["borrowed", "idle", "shared"])
async def test_close_stops_only_an_owned_runtime_no_other_client_uses(
    tmp_path, monkeypatch, runtime_server, asynchronous, runtime_use
):
    from types import SimpleNamespace

    from hai_agents.sessions.client import AsyncSessionsClient, SessionsClient

    stopped = []
    runtime_server.active = ["mine", "another-client-run"] if runtime_use == "shared" else ["mine"]
    runtime = _owned_runtime(runtime_server, tmp_path, monkeypatch, stopped)
    monkeypatch.setattr(LocalRuntime, "ensure_started", lambda **options: runtime)
    monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kwargs: SimpleNamespace(id="mine"))

    async def async_create(self, **kwargs):
        return SimpleNamespace(id="mine")

    monkeypatch.setattr(AsyncSessionsClient, "create_session", async_create)
    options = {"runtime": runtime} if runtime_use == "borrowed" else {}
    if asynchronous:
        client = await AsyncClient.local(auto_bridges=False, **options)
        await client.sessions.create_session(agent="h/agent", messages="hi")
        await client.aclose()
    else:
        client = Client.local(auto_bridges=False, **options)
        client.sessions.create_session(agent="h/agent", messages="hi")
        client.close()
    assert stopped == ([True] if runtime_use == "idle" else [])
    assert client._client_wrapper.httpx_client.httpx_client.is_closed


def test_last_client_of_the_spawning_process_stops_the_runtime(tmp_path, monkeypatch, runtime_server):
    from types import SimpleNamespace

    from hai_agents.sessions.client import SessionsClient

    stopped = []
    spawned = _owned_runtime(runtime_server, tmp_path, monkeypatch, stopped)
    spawned._proc = SimpleNamespace(poll=lambda: None)
    write_owner_only(token_file_path(runtime_server.port, cache_dir=tmp_path), runtime_server.token)
    attached = LocalRuntime.attach(port=runtime_server.port, cache_dir=tmp_path)
    assert attached is not None and not attached.owned
    starts = iter([spawned, attached, attached])
    monkeypatch.setattr(LocalRuntime, "ensure_started", lambda **options: next(starts))
    monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kwargs: SimpleNamespace(id="theirs"))

    spawner = Client.local(auto_bridges=False)
    later = Client.local(auto_bridges=False)
    later.sessions.create_session(agent="h/agent", messages="hi")
    runtime_server.active = ["theirs"]
    spawner.close()
    assert stopped == [], "the spawner must not kill a runtime another client of its process still uses"
    later.close()
    assert stopped == [True], "the last client of the spawning process stops the runtime"

    spawned._proc = SimpleNamespace(poll=lambda: 0)
    runtime_server.active = []
    stranger = Client.local(auto_bridges=False)
    stranger.close()
    assert stopped == [True], "a runtime this process did not spawn is never stopped"


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


def test_idle_shutdown_waits_for_a_concurrent_startup(tmp_path, runtime_server):
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor

    from hai_agents_local.runtime import runtime as module

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    token_file = write_owner_only(token_file_path(runtime_server.port, cache_dir=tmp_path), runtime_server.token)
    runtime = LocalRuntime(
        base_url=f"http://127.0.0.1:{runtime_server.port}",
        api_key=runtime_server.token,
        pid=proc.pid,
        version=None,
        log_path=None,
        owned=True,
        cache_dir=tmp_path,
        port=runtime_server.port,
        proc=proc,
        token_file=token_file,
    )
    try:
        with ThreadPoolExecutor() as pool:
            with module._startup_lock(tmp_path, runtime_server.port, 1):
                stopping = pool.submit(runtime.shutdown_if_idle)
                with pytest.raises(TimeoutError):
                    stopping.result(timeout=0.2)
                assert proc.poll() is None and not runtime_server.requests
            assert stopping.result(timeout=10)
        assert proc.poll() is not None and not token_file.exists()
    finally:
        proc.kill()
        proc.wait()


def test_idle_shutdown_stops_an_owned_runtime_that_cannot_answer(tmp_path):
    import socket
    import subprocess
    import sys

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    token_file = write_owner_only(token_file_path(port, cache_dir=tmp_path), "token")
    runtime = LocalRuntime(
        base_url=f"http://127.0.0.1:{port}",
        api_key="token",
        pid=proc.pid,
        version=None,
        log_path=None,
        owned=True,
        cache_dir=tmp_path,
        port=port,
        proc=proc,
        token_file=token_file,
    )
    try:
        assert runtime.shutdown_if_idle()
        assert proc.poll() is not None and not token_file.exists()
    finally:
        proc.kill()
        proc.wait()


def test_spawner_never_overwrites_the_live_runtime_token(tmp_path, monkeypatch, runtime_server):
    import sys

    token_file = write_owner_only(token_file_path(runtime_server.port, cache_dir=tmp_path), runtime_server.token)
    monkeypatch.setattr(LocalRuntime, "_attach", lambda **kwargs: None)
    with pytest.raises(LocalRuntimeError, match="did not prove"):
        LocalRuntime.ensure_started(
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
            cache_dir=tmp_path,
            port=runtime_server.port,
            timeout_s=5,
        )
    assert token_file.read_text() == runtime_server.token


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

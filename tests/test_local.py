import asyncio
import threading
import time
from typing import Any

import httpx
import pytest

import hai_agents.local.lease as lease_module
from hai_agents import Client
from hai_agents.agents.client import AgentsClient
from hai_agents.local import (
    BridgeBusyError,
    BridgeManager,
    LocalBridge,
    PyautoguiDesktopBridge,
    SeleniumBrowserBridge,
    session_id_from_environment_id,
)
from hai_agents.local.config import AUTO_BRIDGE_ENV_VAR
from hai_agents.local.errors import AuthError
from hai_agents.local.lease import MachineLease
from hai_agents.local.routing import SessionRouter
from hai_agents.local.transport import serialize_result
from hai_agents.sessions.client import SessionsClient

API_KEY = "test-key"

ROUTER = SessionRouter(lambda: API_KEY)


@pytest.fixture(autouse=True)
def _lease_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(lease_module, "LEASE_DIR", tmp_path / "leases")


class TestRoutingKey:
    def test_deterministic_and_kind_scoped(self):
        a = session_id_from_environment_id("m", "k", "desktop")
        assert a == session_id_from_environment_id("m", "k", "desktop")
        assert a != session_id_from_environment_id("m", "k", "web")
        assert a != session_id_from_environment_id("m", "other", "desktop")

    def test_bridge_defaults_api_key_from_env_and_derives_session(self, monkeypatch):
        monkeypatch.setenv("HAI_API_KEY", "envkey")
        bridge = PyautoguiDesktopBridge("m")
        assert bridge.api_key == "envkey"
        assert bridge.session_id == session_id_from_environment_id("m", "envkey", "desktop")

    def test_bridge_without_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("HAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="api_key is required"):
            PyautoguiDesktopBridge("m")


class TestRouter:
    def test_user_device_envs_get_session_ids(self):
        web, desktop, default = ROUTER.stamp_environments(
            [
                {"id": "laptop", "kind": "web", "host": "user_device"},
                {"id": "box", "kind": "desktop", "host": "user_device"},
                {"id": "nokind", "host": "user_device"},
            ]
        )
        assert web["session_id"] == session_id_from_environment_id("laptop", API_KEY, "web")
        assert desktop["session_id"] == session_id_from_environment_id("box", API_KEY, "desktop")
        assert default["session_id"] == session_id_from_environment_id("nokind", API_KEY, "web")

    def test_remote_and_explicit_session_left_alone(self):
        envs = ROUTER.stamp_environments(
            [
                {"id": "remote", "kind": "web"},
                {"id": "pinned", "kind": "web", "host": "user_device", "session_id": "keep"},
                "agent-name-ref",
            ]
        )
        assert "session_id" not in envs[0]
        assert envs[1]["session_id"] == "keep"
        assert envs[2] == "agent-name-ref"
        assert ROUTER.stamp_agent("named-agent") == "named-agent"

    def test_malformed_user_device_env_raises(self):
        with pytest.raises(ValueError, match="need an id"):
            ROUTER.stamp_environments([{"kind": "web", "host": "user_device"}])
        with pytest.raises(ValueError, match="supported kinds"):
            ROUTER.stamp_environments([{"id": "phone", "kind": "mobile", "host": "user_device"}])

    def test_unsupported_user_device_env_type_raises(self):
        class WeirdEnv:
            host = "user_device"
            kind = "web"
            id = "laptop"

        with pytest.raises(TypeError, match="session_id"):
            ROUTER.stamp_environments([WeirdEnv()])

    def test_pydantic_env_model_autowires(self):
        from hai_agents.types.browser import Browser

        [env] = ROUTER.stamp_environments([Browser(id="laptop", kind="web", host="user_device")])
        assert getattr(env, "session_id") == session_id_from_environment_id("laptop", API_KEY, "web")

        [remote] = ROUTER.stamp_environments([Browser(id="cloud", kind="web")])
        assert getattr(remote, "session_id", None) is None

    def test_client_create_agent_autowires(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(AgentsClient, "create_agent", lambda self, **kw: captured.update(kw))
        Client(api_key=API_KEY).agents.create_agent(
            name="local-web",
            description="d",
            environments=[{"id": "laptop", "kind": "web", "host": "user_device"}],
        )
        assert captured["environments"][0]["session_id"] == session_id_from_environment_id("laptop", API_KEY, "web")

    def test_client_create_agent_wires_subagents(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(AgentsClient, "create_agent", lambda self, **kw: captured.update(kw))
        Client(api_key=API_KEY).agents.create_agent(
            name="orchestrator",
            description="d",
            subagents=[{"name": "child", "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}]}],
        )
        env = captured["subagents"][0]["environments"][0]
        assert env["session_id"] == session_id_from_environment_id("box", API_KEY, "desktop")

    def test_client_create_session_autowires_inline_agent(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: captured.update(kw))
        Client(api_key=API_KEY).sessions.create_session(
            agent={"name": "x", "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}]},
            messages="hi",
        )
        env = captured["agent"]["environments"][0]
        assert env["session_id"] == session_id_from_environment_id("box", API_KEY, "desktop")


class TestAutoStart:
    def test_create_session_auto_starts_bridges(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        started: list = []
        monkeypatch.setattr("hai_agents.client.ensure_bridges", started.extend)
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: None)
        Client(api_key=API_KEY).sessions.create_session(
            agent={
                "name": "x",
                "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}],
                "subagents": [
                    {"name": "child", "environments": [{"id": "laptop", "kind": "web", "host": "user_device"}]}
                ],
            },
            messages="hi",
        )
        assert [(b.environment_kind, b.environment_id) for b in started] == [("desktop", "box"), ("web", "laptop")]
        assert isinstance(started[0], PyautoguiDesktopBridge) and isinstance(started[1], SeleniumBrowserBridge)
        assert started[0].session_id == session_id_from_environment_id("box", API_KEY, "desktop")

    def test_named_agent_fetches_resolved_definition_for_bridges(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        started: list = []
        monkeypatch.setattr("hai_agents.client.ensure_bridges", started.extend)
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: None)
        sid = session_id_from_environment_id("box", API_KEY, "desktop")
        calls: dict = {}

        def get_agent(self, name, *, resolve=None):
            calls["resolve"] = resolve
            return {
                "name": name,
                "environments": [{"id": "box", "kind": "desktop", "host": "user_device", "session_id": sid}],
            }

        monkeypatch.setattr(AgentsClient, "get_agent", get_agent)
        Client(api_key=API_KEY).sessions.create_session(agent="my-agent", messages="hi")
        assert calls["resolve"] is True
        assert [(b.environment_kind, b.environment_id, b.session_id) for b in started] == [("desktop", "box", sid)]

    def test_named_agent_without_session_id_raises(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: None)
        monkeypatch.setattr(
            AgentsClient,
            "get_agent",
            lambda self, name, *, resolve=None: {
                "name": name,
                "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}],
            },
        )
        with pytest.raises(RuntimeError, match="no session_id"):
            Client(api_key=API_KEY).sessions.create_session(agent="my-agent", messages="hi")

    def test_named_agent_lookup_failure_propagates(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: "session")
        monkeypatch.setattr(
            AgentsClient, "get_agent", lambda self, name, *, resolve=None: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError, match="boom"):
            Client(api_key=API_KEY).sessions.create_session(agent="ghost", messages="hi")

    def test_string_subagents_resolved_for_bridges(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        started: list = []
        monkeypatch.setattr("hai_agents.client.ensure_bridges", started.extend)
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: None)
        sid = session_id_from_environment_id("laptop", API_KEY, "web")
        monkeypatch.setattr(
            AgentsClient,
            "get_agent",
            lambda self, name, *, resolve=None: {
                "name": name,
                "environments": [{"id": "laptop", "kind": "web", "host": "user_device", "session_id": sid}],
            },
        )
        Client(api_key=API_KEY).sessions.create_session(
            agent={"name": "orchestrator", "subagents": ["helper"]},
            messages="hi",
        )
        assert [(b.environment_kind, b.environment_id, b.session_id) for b in started] == [("web", "laptop", sid)]

    def test_create_session_failure_stops_newly_started_bridges(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        stopped: list = []
        monkeypatch.setattr("hai_agents.client.ensure_bridges", lambda bridges: ["new-sid"])
        monkeypatch.setattr("hai_agents.client.stop_bridges", stopped.extend)
        monkeypatch.setattr(
            SessionsClient, "create_session", lambda self, **kw: (_ for _ in ()).throw(RuntimeError("api down"))
        )
        with pytest.raises(RuntimeError, match="api down"):
            Client(api_key=API_KEY).sessions.create_session(
                agent={"name": "x", "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}]},
                messages="hi",
            )
        assert stopped == ["new-sid"]

    def test_no_bridges_when_disabled(self, monkeypatch):
        started: list = []
        monkeypatch.setattr("hai_agents.client.ensure_bridges", started.extend)
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: None)
        Client(api_key=API_KEY).sessions.create_session(
            agent={"name": "x", "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}]},
            messages="hi",
        )
        assert started == []


class FakeDriver:
    def __init__(self) -> None:
        self.clicks = 0

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.clicks += 1

    def execute_script(self, script: str, *args: Any, n_unsafe_attempts: int = 2) -> Any:
        return {"script": script, "args": list(args), "attempts": n_unsafe_attempts}

    def boom(self) -> None:
        raise RuntimeError("kaboom")

    def _internal(self) -> str:
        return "leak"


class FakeBridge(LocalBridge):
    environment_kind = "desktop"

    def create_driver(self) -> Any:
        return FakeDriver()

    def driver_interface(self) -> type:
        return FakeDriver


class FakeExchange:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    async def post_result(
        self, command_id: str, *, command_uid: str, result: Any, error: str | None, timeout: float
    ) -> bool:
        self.posts.append({"id": command_id, "command_uid": command_uid, "result": result, "error": error})
        return True


def _bridge(driver: Any) -> FakeBridge:
    bridge = FakeBridge("m", api_key="k")
    bridge._driver = driver
    return bridge


class TestBridgeProtocol:
    def test_bytes_results_are_base64(self):
        assert serialize_result(b"abc") == "YWJj"
        assert serialize_result({"png": b"abc"}) == {"png": "YWJj"}

    def test_commands_come_from_the_driver_interface(self):
        assert _bridge(FakeDriver()).commands == {"click", "execute_script", "boom"}

    def test_unknown_and_private_names_return_errors(self):
        bridge = _bridge(FakeDriver())
        for name in ("frobnicate", "_internal"):
            result, error = bridge._dispatch(name, {})
            assert result is None and "not supported" in error

    def test_driver_exception_becomes_error(self):
        result, error = _bridge(FakeDriver())._dispatch("boom", {})
        assert result is None and "kaboom" in error

    def test_var_positional_args_are_splatted(self):
        result, error = _bridge(FakeDriver())._dispatch(
            "execute_script", {"script": "return 1;", "args": [1, "two"], "n_unsafe_attempts": 3}
        )
        assert error is None
        assert result == {"script": "return 1;", "args": [1, "two"], "attempts": 3}

    async def test_each_command_executes_once_and_result_posted(self):
        driver = FakeDriver()
        bridge = _bridge(driver)
        exchange = FakeExchange()
        cmd = {"id": "c1", "command_uid": "u1", "name": "click", "args": {"x": 0, "y": 0}}
        await bridge._process_commands(exchange, [cmd, {**cmd, "id": "c2", "command_uid": "u2"}])
        assert driver.clicks == 2
        assert [p["command_uid"] for p in exchange.posts] == ["u1", "u2"]

    async def test_redelivered_uid_reposts_cached_result_without_reexecuting(self):
        driver = FakeDriver()
        bridge = _bridge(driver)
        exchange = FakeExchange()
        cmd = {"id": "c1", "command_uid": "u1", "name": "click", "args": {"x": 0, "y": 0}}
        await bridge._process_commands(exchange, [cmd])
        await bridge._process_commands(exchange, [{**cmd, "id": "c1-retry"}])
        assert driver.clicks == 1
        assert [p["command_uid"] for p in exchange.posts] == ["u1", "u1"]

    async def test_auth_error_mid_poll_propagates(self):
        bridge = _bridge(FakeDriver())

        class AuthFailingExchange:
            async def fetch_commands(self, *args: Any, **kwargs: Any) -> None:
                raise AuthError("key revoked")

        with pytest.raises(AuthError):
            await bridge._poll_loop(AuthFailingExchange())

    async def test_permanent_4xx_in_poll_loop_propagates(self):
        bridge = _bridge(FakeDriver())

        class BadRequestExchange:
            async def fetch_commands(self, *args: Any, **kwargs: Any) -> None:
                request = httpx.Request("GET", "http://test")
                raise httpx.HTTPStatusError(
                    "bad request", request=request, response=httpx.Response(400, request=request)
                )

        with pytest.raises(httpx.HTTPStatusError):
            await bridge._poll_loop(BadRequestExchange())

    async def test_post_result_auth_failure_propagates(self):
        bridge = _bridge(FakeDriver())

        class AuthPostExchange:
            async def post_result(self, *args: Any, **kwargs: Any) -> bool:
                raise AuthError("key revoked")

        cmd = {"id": "c1", "command_uid": "u1", "name": "click", "args": {"x": 0, "y": 0}}
        with pytest.raises(AuthError):
            await bridge._process_commands(AuthPostExchange(), [cmd])

    def test_kind_lease_is_machine_wide(self):
        first = MachineLease("desktop", "sid-1")
        first.acquire()
        try:
            with pytest.raises(BridgeBusyError):
                MachineLease("desktop", "sid-1").acquire()
            with pytest.raises(RuntimeError, match="already serves"):
                MachineLease("desktop", "sid-2").acquire()
        finally:
            first.release()

    def test_released_lease_leaves_no_stale_holder(self):
        lease = MachineLease("desktop", "sid-1")
        lease.acquire()
        lease.release()
        assert lease._path.read_text() == ""


class TestDriverInterfaces:
    def test_browser_commands_match_hai_drivers_interface(self):
        pytest.importorskip("hai_drivers.web.interface")
        commands = SeleniumBrowserBridge("m", api_key="k").commands
        assert {"goto", "click_at", "press_key", "screenshot_b64", "get_tabs"} <= commands
        assert not any(name.startswith("_") for name in commands)

    def test_desktop_commands_match_hai_drivers_interface(self):
        pytest.importorskip("hai_drivers.desktop.interface")
        commands = PyautoguiDesktopBridge("m", api_key="k").commands
        assert {"click", "write", "run_command", "read_file", "screenshot_b64"} <= commands
        assert not any(name.startswith("_") for name in commands)


class ServingBridge(FakeBridge):
    def __init__(self, environment_id: str, **kwargs: Any) -> None:
        super().__init__(environment_id, **kwargs)
        self._serving = None

    async def run(self) -> None:
        self._serving = asyncio.Event()
        self.ready.set()
        await self._serving.wait()

    def request_stop(self) -> None:
        if self._serving is not None:
            self._serving.set()


class BrowserServingBridge(ServingBridge):
    environment_kind = "web"


class TestManager:
    @pytest.fixture
    def manager(self):
        manager = BridgeManager()
        yield manager
        manager.stop_all()

    def test_startup_failure_surfaces_to_caller(self, manager):
        class FailingBridge(ServingBridge):
            async def run(self):
                raise AuthError("bad key")

        with pytest.raises(RuntimeError) as exc_info:
            manager.ensure([FailingBridge("laptop", api_key="k")])
        assert isinstance(exc_info.value.__cause__, AuthError)

    def test_readiness_timeout_raises(self, manager, monkeypatch):
        class NeverReadyBridge(ServingBridge):
            async def run(self):
                self._serving = asyncio.Event()
                await self._serving.wait()

        import hai_agents.local.manager as manager_module

        monkeypatch.setattr(manager_module, "READY_TIMEOUT_S", 0.05)
        with pytest.raises(RuntimeError, match="not ready"):
            manager.ensure([NeverReadyBridge("laptop", api_key="k")])
        assert manager._runners == {}

    def test_busy_bridge_stands_by_then_takes_over(self, manager, monkeypatch):
        import hai_agents.local.manager as manager_module

        monkeypatch.setattr(manager_module, "TAKEOVER_POLL_S", 0.02)

        class LeasedServingBridge(ServingBridge):
            async def run(self):
                self._lease.acquire()
                try:
                    await super().run()
                finally:
                    self._lease.release()

        bridge = LeasedServingBridge("laptop", api_key="k")
        holder = MachineLease("desktop", bridge.session_id)
        holder.acquire()
        try:
            assert manager.ensure([bridge]) == [bridge.session_id]
            assert bridge._serving is None
            assert manager._runners[bridge.session_id].thread.is_alive()
        finally:
            holder.release()
        deadline = time.time() + 5
        while bridge._serving is None and time.time() < deadline:
            time.sleep(0.01)
        assert bridge._serving is not None

    def test_second_environment_on_same_kind_raises(self, manager):
        manager.ensure(
            [
                ServingBridge("laptop", api_key="k"),
                ServingBridge("laptop", api_key="k"),
                BrowserServingBridge("desk", api_key="k"),
            ]
        )
        with pytest.raises(RuntimeError, match="already serves"):
            manager.ensure([ServingBridge("other-laptop", api_key="k")])

    def test_ensure_reports_new_bridges_and_stop_is_targeted(self, manager):
        bridge = ServingBridge("laptop", api_key="k")
        ids = manager.ensure([bridge])
        assert ids == [bridge.session_id]
        assert manager.ensure([ServingBridge("laptop", api_key="k")]) == []
        manager.stop(ids)
        assert manager._runners == {}

    def test_partial_start_is_rolled_back(self, manager):
        with pytest.raises(RuntimeError, match="already serves"):
            manager.ensure(
                [
                    BrowserServingBridge("desk", api_key="k"),
                    ServingBridge("a", api_key="k"),
                    ServingBridge("b", api_key="k"),
                ]
            )
        assert manager._runners == {}

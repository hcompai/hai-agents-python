import asyncio
import threading
from typing import Any

import httpx
import pytest

from hai_agents import Client
from hai_agents.sessions.client import SessionsClient
from hai_agents_local import BridgeManager, LocalBridge, PyautoguiDesktopBridge, SeleniumBrowserBridge
from hai_agents_local.config import AUTO_BRIDGE_ENV_VAR
from hai_agents_local.errors import AuthError
from hai_agents_local.routing import localize_agent
from hai_agents_local.transport import Command, serialize_result

API_KEY = "test-key"


class TestLocalizeAgent:
    def test_unclaimed_user_device_envs_get_bridges_with_fresh_session_ids(self):
        agent = {
            "name": "x",
            "environments": [
                {"host": "user_device"},
                {"id": "box", "kind": "desktop", "host": "user_device"},
            ],
        }
        localized, bridges = localize_agent(agent, api_key=API_KEY)
        envs = localized["environments"]
        assert [type(b) for b in bridges] == [SeleniumBrowserBridge, PyautoguiDesktopBridge]
        assert [e["session_id"] for e in envs] == [b.session_id for b in bridges]
        assert len({b.session_id for b in bridges}) == 2
        assert envs[0]["kind"] == "web"
        assert "session_id" not in agent["environments"][0]

    def test_second_unclaimed_env_of_same_kind_raises(self):
        agent = {
            "name": "orchestrator",
            "environments": [{"id": "laptop", "kind": "web", "host": "user_device"}],
            "subagents": [
                {"name": "child", "environments": [{"id": "laptop-2", "kind": "web", "host": "user_device"}]}
            ],
        }
        with pytest.raises(ValueError, match="multiple user_device web"):
            localize_agent(agent, api_key=API_KEY)

    def test_claimed_env_does_not_count_against_the_kind(self):
        agent = {
            "name": "x",
            "environments": [
                {"id": "pinned", "kind": "web", "host": "user_device", "session_id": "served-elsewhere"},
                {"id": "laptop", "kind": "web", "host": "user_device"},
            ],
        }
        localized, bridges = localize_agent(agent, api_key=API_KEY)
        [bridge] = bridges
        assert localized["environments"][1]["session_id"] == bridge.session_id

    def test_claimed_remote_and_string_targets_left_alone(self):
        agent = {
            "name": "x",
            "environments": [
                {"id": "remote", "kind": "web"},
                {"id": "pinned", "kind": "web", "host": "user_device", "session_id": "keep"},
            ],
            "subagents": ["registered-agent"],
        }
        localized, bridges = localize_agent(agent, api_key=API_KEY)
        assert localized is agent
        assert bridges == []
        assert localize_agent("named-agent", api_key=API_KEY) == ("named-agent", [])

    def test_inline_subagents_are_walked(self):
        agent = {
            "name": "orchestrator",
            "subagents": [{"name": "child", "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}]}],
        }
        localized, bridges = localize_agent(agent, api_key=API_KEY)
        [bridge] = bridges
        assert isinstance(bridge, PyautoguiDesktopBridge)
        assert localized["subagents"][0]["environments"][0]["session_id"] == bridge.session_id

    def test_unsupported_user_device_kind_raises(self):
        with pytest.raises(ValueError, match="supported kinds"):
            localize_agent(
                {"name": "x", "environments": [{"id": "phone", "kind": "mobile", "host": "user_device"}]},
                api_key=API_KEY,
            )

    def test_pydantic_env_model_is_stamped(self):
        from hai_agents.types.browser import Browser

        agent = {"name": "x", "environments": [Browser(id="laptop", host="user_device")]}
        localized, [bridge] = localize_agent(agent, api_key=API_KEY)
        env = localized["environments"][0]
        assert env.session_id == bridge.session_id
        assert env.model_dump()["kind"] == "web"

    def test_bare_desktop_model_gets_a_desktop_bridge_and_kind_tag(self):
        from hai_agents.types.desktop import Desktop

        agent = {"name": "x", "environments": [Desktop(id="box", host="user_device")]}
        localized, [bridge] = localize_agent(agent, api_key=API_KEY)
        assert isinstance(bridge, PyautoguiDesktopBridge)
        env = localized["environments"][0]
        assert env.session_id == bridge.session_id
        assert env.model_dump()["kind"] == "desktop"

    def test_bridge_mints_a_fresh_session_id(self):
        bridge = PyautoguiDesktopBridge(api_key=API_KEY)
        assert bridge.session_id
        assert bridge.session_id != PyautoguiDesktopBridge(api_key=API_KEY).session_id

    def test_bridge_without_api_key_raises(self):
        with pytest.raises(ValueError, match="api_key is required"):
            PyautoguiDesktopBridge(api_key="")

    def test_bridge_rejects_non_uuid_session_id(self):
        with pytest.raises(ValueError, match="must be a UUID"):
            PyautoguiDesktopBridge(api_key=API_KEY, session_id="my-laptop-1")


class TestAutoStart:
    def test_create_session_starts_bridges_and_stamps_matching_session_ids(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        started: list = []
        captured: dict = {}
        monkeypatch.setattr("hai_agents_local.sessions.ensure_bridges", lambda bridges: started.extend(bridges) or [])
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: captured.update(kw))
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
        desktop, web = started
        assert isinstance(desktop, PyautoguiDesktopBridge) and isinstance(web, SeleniumBrowserBridge)
        assert captured["agent"]["environments"][0]["session_id"] == desktop.session_id
        assert captured["agent"]["subagents"][0]["environments"][0]["session_id"] == web.session_id

    def test_named_agent_is_passed_through_without_bridges(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        started: list = []
        captured: dict = {}
        monkeypatch.setattr("hai_agents_local.sessions.ensure_bridges", lambda bridges: started.extend(bridges) or [])
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: captured.update(kw))
        Client(api_key=API_KEY).sessions.create_session(agent="my-agent", messages="hi")
        assert started == []
        assert captured["agent"] == "my-agent"

    def test_create_session_failure_stops_newly_started_bridges(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        stopped: list = []
        monkeypatch.setattr("hai_agents_local.sessions.ensure_bridges", lambda bridges: ["new-sid"])
        monkeypatch.setattr("hai_agents_local.sessions.stop_bridges", stopped.extend)
        monkeypatch.setattr(
            SessionsClient, "create_session", lambda self, **kw: (_ for _ in ()).throw(RuntimeError("api down"))
        )
        with pytest.raises(RuntimeError, match="api down"):
            Client(api_key=API_KEY).sessions.create_session(
                agent={"name": "x", "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}]},
                messages="hi",
            )
        assert stopped == ["new-sid"]

    @staticmethod
    def _crash_wiring(monkeypatch, cancelled: list, stopped: list, bridges: list) -> None:
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
        monkeypatch.setattr("hai_agents_local.sessions.stop_bridges", stopped.extend)
        monkeypatch.setattr(SessionsClient, "cancel_session", lambda self, sid: cancelled.append(sid))
        monkeypatch.setattr(
            "hai_agents_local.sessions.ensure_bridges",
            lambda new: bridges.extend(new) or [b.session_id for b in new],
        )

    _TWO_ENV_AGENT = {
        "name": "x",
        "environments": [
            {"id": "box", "kind": "desktop", "host": "user_device"},
            {"id": "laptop", "kind": "web", "host": "user_device"},
        ],
    }

    def test_bridge_loss_cancels_session_once_and_stops_sibling_bridges(self, monkeypatch):
        cancelled: list = []
        stopped: list = []
        bridges: list = []
        self._crash_wiring(monkeypatch, cancelled, stopped, bridges)
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: type("S", (), {"id": "sess-1"})())
        Client(api_key=API_KEY).sessions.create_session(agent=dict(self._TWO_ENV_AGENT), messages="hi")
        bridges[0].on_crash()
        assert cancelled == ["sess-1"]
        assert stopped == [bridge.session_id for bridge in bridges]
        bridges[1].on_crash()
        assert cancelled == ["sess-1"]

    def test_crash_between_startup_and_session_creation_still_cancels(self, monkeypatch):
        cancelled: list = []
        stopped: list = []
        bridges: list = []
        self._crash_wiring(monkeypatch, cancelled, stopped, bridges)

        def create_and_crash(self, **kw):
            bridges[0].on_crash()
            return type("S", (), {"id": "sess-2"})()

        monkeypatch.setattr(SessionsClient, "create_session", create_and_crash)
        Client(api_key=API_KEY).sessions.create_session(agent=dict(self._TWO_ENV_AGENT), messages="hi")
        assert cancelled == ["sess-2"]
        assert stopped == [bridge.session_id for bridge in bridges]

    async def test_async_crash_before_session_creation_cancels_off_the_loop(self, monkeypatch):
        from hai_agents import AsyncClient
        from hai_agents.sessions.client import AsyncSessionsClient

        cancelled: list = []
        stopped: list = []
        bridges: list = []
        self._crash_wiring(monkeypatch, cancelled, stopped, bridges)

        async def create_and_crash(self, **kw):
            bridges[0].on_crash()
            return type("S", (), {"id": "sess-3"})()

        monkeypatch.setattr(AsyncSessionsClient, "create_session", create_and_crash)
        await AsyncClient(api_key=API_KEY).sessions.create_session(agent=dict(self._TWO_ENV_AGENT), messages="hi")
        assert cancelled == ["sess-3"]
        assert stopped == [bridge.session_id for bridge in bridges]

    def test_no_bridges_and_no_stamping_when_disabled(self, monkeypatch):
        monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "0")
        started: list = []
        captured: dict = {}
        monkeypatch.setattr("hai_agents_local.sessions.ensure_bridges", lambda bridges: started.extend(bridges) or [])
        monkeypatch.setattr(SessionsClient, "create_session", lambda self, **kw: captured.update(kw))
        Client(api_key=API_KEY).sessions.create_session(
            agent={"name": "x", "environments": [{"id": "box", "kind": "desktop", "host": "user_device"}]},
            messages="hi",
        )
        assert started == []
        assert "session_id" not in captured["agent"]["environments"][0]


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
    ) -> None:
        self.posts.append({"id": command_id, "command_uid": command_uid, "result": result, "error": error})


def _bridge(driver: Any) -> FakeBridge:
    bridge = FakeBridge(api_key="k")
    bridge._driver = driver
    return bridge


class TestChannelSetup:
    async def test_429_is_retried_with_backoff_then_succeeds(self, monkeypatch):
        import hai_agents_local.bridge as bridge_module

        async def instant_sleep(self, seconds: float) -> bool:
            return False

        monkeypatch.setattr(FakeBridge, "_interruptible_sleep", instant_sleep)
        calls = {"n": 0}

        def responder(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, headers={"Retry-After": "0"}) if calls["n"] < 3 else httpx.Response(200)

        bridge = FakeBridge(api_key="k")
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
            exchange = bridge_module.CommandExchange(client, "http://test")
            assert await bridge._open_channel(exchange) is True
        assert calls["n"] == 3

    async def test_429_gives_up_with_a_clear_error(self, monkeypatch):
        async def instant_sleep(self, seconds: float) -> bool:
            return False

        monkeypatch.setattr(FakeBridge, "_interruptible_sleep", instant_sleep)
        from hai_agents_local.transport import CommandExchange

        bridge = FakeBridge(api_key="k")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(429, headers={"Retry-After": "0"}))
        ) as client:
            with pytest.raises(RuntimeError, match="rate-limiting"):
                await bridge._open_channel(CommandExchange(client, "http://test"))

    async def test_auth_error_is_not_retried(self):
        from hai_agents_local.transport import CommandExchange

        bridge = FakeBridge(api_key="k")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
            with pytest.raises(AuthError):
                await bridge._open_channel(CommandExchange(client, "http://test"))


class TestMacosPermissionPreflight:
    def _fake_frameworks(self, monkeypatch, *, ax: bool, screen: bool):
        import sys as _sys
        import types

        apps = types.ModuleType("ApplicationServices")
        apps.kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"
        apps.AXIsProcessTrustedWithOptions = lambda options: ax
        quartz = types.ModuleType("Quartz")
        quartz.CGPreflightScreenCaptureAccess = lambda: screen
        quartz.CGRequestScreenCaptureAccess = lambda: screen
        monkeypatch.setitem(_sys.modules, "ApplicationServices", apps)
        monkeypatch.setitem(_sys.modules, "Quartz", quartz)
        monkeypatch.setattr("hai_agents_local.desktop.sys.platform", "darwin")

    def test_missing_grants_fail_fast_with_instructions(self, monkeypatch):
        from hai_agents_local.desktop import ensure_macos_input_permissions

        self._fake_frameworks(monkeypatch, ax=False, screen=True)
        with pytest.raises(PermissionError, match="Accessibility"):
            ensure_macos_input_permissions()
        self._fake_frameworks(monkeypatch, ax=True, screen=False)
        with pytest.raises(PermissionError, match="Screen Recording"):
            ensure_macos_input_permissions()

    def test_granted_passes(self, monkeypatch):
        from hai_agents_local.desktop import ensure_macos_input_permissions

        self._fake_frameworks(monkeypatch, ax=True, screen=True)
        ensure_macos_input_permissions()


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
        cmd = Command(id="c1", command_uid="u1", name="click", args={"x": 0, "y": 0})
        await bridge._process_commands(exchange, [cmd, cmd.model_copy(update={"id": "c2", "command_uid": "u2"})])
        assert driver.clicks == 2
        assert [p["command_uid"] for p in exchange.posts] == ["u1", "u2"]

    async def test_redelivered_uid_reposts_cached_result_without_reexecuting(self):
        driver = FakeDriver()
        bridge = _bridge(driver)
        exchange = FakeExchange()
        cmd = Command(id="c1", command_uid="u1", name="click", args={"x": 0, "y": 0})
        await bridge._process_commands(exchange, [cmd])
        await bridge._process_commands(exchange, [cmd.model_copy(update={"id": "c1-retry"})])
        assert driver.clicks == 1
        assert [p["command_uid"] for p in exchange.posts] == ["u1", "u1"]

    async def test_undeliverable_result_raises_after_retries(self, monkeypatch):
        import hai_agents_local.bridge as bridge_module

        monkeypatch.setattr(bridge_module, "POST_RESULT_RETRIES", 1)
        bridge = _bridge(FakeDriver())
        attempts = []

        class FailingPostExchange:
            async def post_result(self, *args: Any, **kwargs: Any) -> None:
                attempts.append(1)
                request = httpx.Request("POST", "http://test")
                raise httpx.HTTPStatusError(
                    "bad gateway", request=request, response=httpx.Response(502, request=request)
                )

        with pytest.raises(httpx.HTTPStatusError):
            await bridge._deliver(FailingPostExchange(), "c1", "u1", None, None)
        assert len(attempts) == 2

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
            async def post_result(self, *args: Any, **kwargs: Any) -> None:
                raise AuthError("key revoked")

        cmd = Command(id="c1", command_uid="u1", name="click", args={"x": 0, "y": 0})
        with pytest.raises(AuthError):
            await bridge._process_commands(AuthPostExchange(), [cmd])


class TestDriverInterfaces:
    def test_browser_commands_match_hai_drivers_interface(self):
        pytest.importorskip("hai_drivers.web.interface")
        commands = SeleniumBrowserBridge(api_key="k").commands
        assert {"goto", "click_at", "press_key", "screenshot_b64", "get_tabs"} <= commands
        assert not any(name.startswith("_") for name in commands)

    def test_desktop_commands_match_hai_drivers_interface(self):
        pytest.importorskip("hai_drivers.desktop.interface")
        commands = PyautoguiDesktopBridge(api_key="k").commands
        assert {"click", "write", "run_command", "read_file", "screenshot_b64"} <= commands
        assert not any(name.startswith("_") for name in commands)


class ServingBridge(FakeBridge):
    def __init__(self, environment_id: str | None = None, **kwargs: Any) -> None:
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

    def test_startup_failure_surfaces_to_caller_without_firing_on_crash(self, manager):
        crashed = threading.Event()

        class FailingBridge(ServingBridge):
            async def run(self):
                raise AuthError("bad key")

        bridge = FailingBridge(api_key="k")
        bridge.on_crash = crashed.set
        with pytest.raises(RuntimeError) as exc_info:
            manager.ensure([bridge])
        assert isinstance(exc_info.value.__cause__, AuthError)
        assert not crashed.is_set()

    def test_readiness_timeout_raises(self, manager, monkeypatch):
        class NeverReadyBridge(ServingBridge):
            async def run(self):
                self._serving = asyncio.Event()
                await self._serving.wait()

        import hai_agents_local.manager as manager_module

        monkeypatch.setattr(manager_module, "READY_TIMEOUT_S", 0.05)
        with pytest.raises(RuntimeError, match="not ready"):
            manager.ensure([NeverReadyBridge(api_key="k")])
        assert manager._runners == {}

    def test_newer_session_takes_over_the_kind_and_notifies_the_displaced(self, manager):
        first = ServingBridge(api_key="k")
        second = ServingBridge(api_key="k")
        browser = BrowserServingBridge(api_key="k")
        first_lost, second_lost = threading.Event(), threading.Event()
        first.on_crash = first_lost.set
        second.on_crash = second_lost.set
        manager.ensure([first, browser])
        first_runner = manager._runners[first.session_id]
        manager.ensure([second])
        assert first.session_id not in manager._runners
        assert not first_runner.thread.is_alive()
        assert first_lost.is_set()
        assert not second_lost.is_set()
        assert manager._runners[second.session_id].thread.is_alive()
        assert manager._runners[browser.session_id].thread.is_alive()

    def test_ensure_reports_new_bridges_and_stop_is_targeted(self, manager):
        bridge = ServingBridge(api_key="k")
        ids = manager.ensure([bridge])
        assert ids == [bridge.session_id]
        assert manager.ensure([bridge]) == []
        manager.stop(ids)
        assert manager._runners == {}

    def test_two_same_kind_bridges_in_one_batch_raise(self, manager):
        with pytest.raises(RuntimeError, match="two local desktop"):
            manager.ensure(
                [
                    BrowserServingBridge(api_key="k"),
                    ServingBridge(api_key="k"),
                    ServingBridge(api_key="k"),
                ]
            )
        assert manager._runners == {}

    def test_restarted_bridge_serves_again_on_a_fresh_loop(self, manager, monkeypatch):
        class IdleExchange:
            def __init__(self, client: Any, base_url: str) -> None:
                pass

            async def ensure_channel(self, session_id: str) -> None:
                pass

            async def fetch_commands(self, session_id: str, **kwargs: Any) -> None:
                await asyncio.sleep(0.01)
                return None

        import hai_agents_local.bridge as bridge_module

        monkeypatch.setattr(bridge_module, "CommandExchange", IdleExchange)
        bridge = FakeBridge(api_key="k")
        crashed = threading.Event()
        bridge.on_crash = crashed.set
        assert manager.ensure([bridge]) == [bridge.session_id]
        manager.stop([bridge.session_id])
        assert manager.ensure([bridge]) == [bridge.session_id]
        assert not crashed.wait(0.5)
        assert manager._runners[bridge.session_id].thread.is_alive()
        manager.stop([bridge.session_id])

    def test_crash_after_ready_fires_on_crash(self, manager):
        crashed = threading.Event()

        class CrashingBridge(ServingBridge):
            async def run(self):
                self.ready.set()
                await asyncio.sleep(0.2)
                raise RuntimeError("boom mid-session")

        bridge = CrashingBridge(api_key="k")
        bridge.on_crash = crashed.set
        manager.ensure([bridge])
        assert crashed.wait(5.0)

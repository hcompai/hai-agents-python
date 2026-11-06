from __future__ import annotations

import threading
import types
from typing import Any

import pytest

from hai_agents_local import HoloTabBrowserBridge, SeleniumBrowserBridge, routing
from hai_agents_local.config import AUTO_BRIDGE_ENV_VAR, LOCAL_BROWSER_ENV_VAR
from hai_agents_local.holotab import connect

API_KEY = "test-key"
WEB_AGENT = {"name": "x", "environments": [{"id": "laptop", "kind": "web", "host": "user_device"}]}


class FakeLink:
    def __init__(self, connected: bool = False, arrives: bool = False) -> None:
        self.connected = connected
        self.arrives = arrives
        self.started = 0
        self.waited: list[float] = []

    def start(self) -> None:
        self.started += 1

    def wait_connected(self, seconds: float) -> bool:
        self.waited.append(seconds)
        return self.arrives


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"registered": True, "installs": 0, "install_error": None, "link": FakeLink()}

    def install_host(**_: Any) -> None:
        state["installs"] += 1
        if state["install_error"]:
            raise state["install_error"]

    monkeypatch.setattr(connect, "process_link", lambda: state["link"])
    monkeypatch.setattr(connect.install, "host_registered", lambda: state["registered"])
    monkeypatch.setattr(connect.install, "install_host", install_host)
    monkeypatch.setattr(connect, "_failed_at", None)
    monkeypatch.setattr(connect, "_first_use_until", 0.0)
    return state


def test_a_connected_holotab_serves_user_device_web(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routing, "holotab_connected", lambda: True)
    localized, [bridge], _ = routing.localize_agent(WEB_AGENT, api_key=API_KEY)

    assert isinstance(bridge, HoloTabBrowserBridge)
    assert localized["environments"][0]["session_id"] == bridge.session_id


def test_without_holotab_user_device_web_stays_on_selenium() -> None:
    _, [bridge], _ = routing.localize_agent(WEB_AGENT, api_key=API_KEY)
    assert isinstance(bridge, SeleniumBrowserBridge)


@pytest.mark.parametrize(
    ("choice", "connected", "expected"),
    [
        ("holotab", False, HoloTabBrowserBridge),
        ("selenium", True, SeleniumBrowserBridge),
        ("HoloTab", False, HoloTabBrowserBridge),
        ("nonsense", True, HoloTabBrowserBridge),
        ("", False, SeleniumBrowserBridge),
    ],
)
def test_the_environment_variable_forces_one_bridge(
    monkeypatch: pytest.MonkeyPatch, choice: str, connected: bool, expected: type
) -> None:
    probed: list[int] = []
    installed: list[int] = []
    monkeypatch.setattr(routing, "holotab_connected", lambda: probed.append(1) or connected)
    monkeypatch.setattr(routing, "install_host", lambda: installed.append(1))
    monkeypatch.setenv(LOCAL_BROWSER_ENV_VAR, choice)

    assert routing.browser_bridge_type() is expected
    assert bool(probed) is (choice not in {"holotab", "selenium", "HoloTab"})
    assert bool(installed) is (choice in {"holotab", "HoloTab"})


def test_the_bridge_kinds_a_session_needs_are_known_without_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routing, "holotab_connected", lambda: pytest.fail("probed"))
    assert [t.environment_kind for t in routing.local_bridge_types(WEB_AGENT)] == ["web"]


def test_the_serve_hint_names_both_browser_commands() -> None:
    hint = routing.SERVE_COMMANDS["web"]
    assert "--holotab" in hint and "--selenium" in hint


def test_a_second_local_web_env_names_both_flags_in_its_error() -> None:
    agent = {
        "name": "x",
        "environments": [{"id": "a", "kind": "web", "host": "user_device"}],
        "subagents": [{"name": "c", "environments": [{"id": "b", "kind": "web", "host": "user_device"}]}],
    }
    with pytest.raises(ValueError, match=r"--holotab\|--selenium"):
        routing.localize_agent(agent, api_key=API_KEY)


def test_a_connected_link_answers_at_once(probe: dict[str, Any]) -> None:
    probe["link"] = FakeLink(connected=True)
    assert connect.holotab_connected() is True
    assert probe["installs"] == 0 and probe["link"].waited == []


def test_a_registered_host_is_waited_for_briefly(probe: dict[str, Any]) -> None:
    probe["link"] = FakeLink(arrives=True)
    assert connect.holotab_connected() is True
    assert probe["link"].waited == [connect.PROBE_WAIT_S]
    assert probe["installs"] == 1 and probe["link"].started == 1


def test_a_manifest_written_just_now_waits_for_holotabs_retry_alarm(probe: dict[str, Any]) -> None:
    probe["registered"] = False
    assert connect.holotab_connected() is False
    assert probe["link"].waited == [connect.FIRST_USE_WAIT_S] == [65.0]


def test_a_miss_is_remembered_so_each_session_does_not_wait_again(
    probe: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert connect.holotab_connected() is False
    assert connect.holotab_connected() is False
    assert probe["link"].waited == [connect.PROBE_WAIT_S]

    monkeypatch.setattr(connect.time, "monotonic", lambda: 1e12)
    connect.holotab_connected()
    assert len(probe["link"].waited) == 2


@pytest.mark.parametrize("error", [PermissionError("read-only home"), RuntimeError("unsafe socket path")])
def test_a_host_that_cannot_be_registered_means_not_connected(probe: dict[str, Any], error: Exception) -> None:
    probe["install_error"] = error
    assert connect.holotab_connected() is False
    assert probe["link"].waited == []


def test_the_probe_waits_for_chrome_without_holding_its_lock(probe: dict[str, Any]) -> None:
    held: list[bool] = []
    link = probe["link"]
    link.wait_connected = lambda seconds: held.append(connect._lock.locked()) or False
    assert connect.holotab_connected() is False
    assert held == [False]


def test_a_probe_beside_a_first_use_wait_waits_as_long_as_it(probe: dict[str, Any]) -> None:
    probe["registered"] = False
    connect.holotab_connected()
    probe["registered"] = True
    connect._failed_at = None
    connect.holotab_connected()
    first, second = probe["link"].waited
    assert first == connect.FIRST_USE_WAIT_S and second > connect.PROBE_WAIT_S


async def test_an_async_session_probes_for_holotab_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from hai_agents import AsyncClient
    from hai_agents.sessions.client import AsyncSessionsClient

    loop_thread = threading.current_thread()
    probed_on: list[threading.Thread] = []
    monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
    monkeypatch.setattr(routing, "holotab_connected", lambda: probed_on.append(threading.current_thread()) or True)
    monkeypatch.setattr(HoloTabBrowserBridge, "preflight", lambda self: None)
    monkeypatch.setattr("hai_agents_local.sessions.ensure_bridges", lambda bridges: [])
    monkeypatch.setattr("hai_agents_local.sessions._ensure_stop_watcher", lambda: None)

    async def create(self: Any, **kwargs: Any) -> Any:
        return types.SimpleNamespace(id=None)

    monkeypatch.setattr(AsyncSessionsClient, "create_session", create)
    async with AsyncClient(api_key=API_KEY) as client:
        await client.sessions.create_session(agent=WEB_AGENT, messages="hi")

    assert probed_on and loop_thread not in probed_on

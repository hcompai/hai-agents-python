from __future__ import annotations

import threading
import types
from typing import Any

import pytest

from hai_agents_local import HoloTabBrowserBridge, SeleniumBrowserBridge, routing
from hai_agents_local.config import AUTO_BRIDGE_ENV_VAR
from hai_agents_local.holotab import connect
from hai_agents_local.holotab.bridge import NOT_CONNECTED

API_KEY = "test-key"
TOO_OLD = "HoloTab is too old for this app: update it from the Chrome Web Store"
WEB_AGENT = {"name": "x", "environments": [{"id": "laptop", "kind": "web", "host": "user_device"}]}
HOLOTAB_AGENT = {"name": "x", "environments": [{"id": "chrome", "kind": "web", "host": "holotab"}]}


class FakeClient:
    def __init__(self, connected: bool = False, arrives_after: float | None = None) -> None:
        self.connected = connected
        self.arrives_after = arrives_after
        self.incompatible: str | None = None
        self.started = 0
        self.waited: list[float] = []

    def start(self) -> None:
        self.started += 1

    def wait_connected(self, seconds: float) -> bool:
        self.waited.append(seconds)
        if self.arrives_after is not None and sum(self.waited) >= self.arrives_after:
            self.connected = True
        return self.connected


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"installs": 0, "install_error": None, "client": FakeClient(), "apps": []}

    def install_host() -> None:
        state["installs"] += 1
        if state["install_error"]:
            raise state["install_error"]

    def process_client(name: str, key: str) -> FakeClient:
        state["apps"].append((name, key))
        return state["client"]

    monkeypatch.setattr(connect, "process_client", process_client)
    monkeypatch.setattr(connect, "install_host", install_host)
    return state


def test_user_device_web_stays_on_selenium_and_touches_nothing_of_holotabs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routing, "require_holotab", lambda *_: pytest.fail("HoloTab was asked for"))
    _, [bridge], _ = routing.localize_agent(WEB_AGENT, api_key=API_KEY)
    assert isinstance(bridge, SeleniumBrowserBridge)


def test_holotab_web_is_served_with_holotab(monkeypatch: pytest.MonkeyPatch) -> None:
    required: list[int] = []
    monkeypatch.setattr(routing, "require_holotab", lambda api_key: required.append(api_key))
    localized, [bridge], _ = routing.localize_agent(HOLOTAB_AGENT, api_key=API_KEY)

    assert isinstance(bridge, HoloTabBrowserBridge)
    assert localized["environments"][0]["session_id"] == bridge.session_id
    assert required == [API_KEY]


def test_a_routed_holotab_bridge_ends_its_session_on_a_refusal_so_the_remote_session_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routing, "require_holotab", lambda *_: None)
    _, [bridge], _ = routing.localize_agent(HOLOTAB_AGENT, api_key=API_KEY)
    assert isinstance(bridge, HoloTabBrowserBridge)
    assert bridge.stop_on_refusal is True


def test_a_holotab_that_cannot_serve_fails_the_session_instead_of_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(*_: Any) -> None:
        raise RuntimeError(NOT_CONNECTED)

    monkeypatch.setattr(routing, "require_holotab", unreachable)
    with pytest.raises(RuntimeError, match="Connect to desktop apps"):
        routing.localize_agent(HOLOTAB_AGENT, api_key=API_KEY)


def test_holotab_serves_only_web() -> None:
    agent = {"name": "x", "environments": [{"id": "box", "kind": "workstation", "host": "holotab"}]}
    with pytest.raises(ValueError, match="holotab environment 'box' has kind 'workstation'"):
        routing.localize_agent(agent, api_key=API_KEY)


@pytest.mark.parametrize(
    ("agent", "expected"), [(WEB_AGENT, SeleniumBrowserBridge), (HOLOTAB_AGENT, HoloTabBrowserBridge)]
)
def test_the_bridge_types_a_session_needs_are_known_without_probing(
    monkeypatch: pytest.MonkeyPatch, agent: dict[str, Any], expected: type
) -> None:
    monkeypatch.setattr(routing, "require_holotab", lambda *_: pytest.fail("probed"))
    assert routing.local_bridge_types(agent) == [expected]


@pytest.mark.parametrize(
    ("host", "hint"),
    [("user_device", "`holo local browser --session-id"), ("holotab", "`holo local browser --holotab")],
)
def test_a_second_local_web_env_names_the_command_for_its_host(host: str, hint: str) -> None:
    agent = {
        "name": "x",
        "environments": [{"id": "a", "kind": "web", "host": host}],
        "subagents": [{"name": "c", "environments": [{"id": "b", "kind": "web", "host": host}]}],
    }
    with pytest.raises(ValueError, match=hint):
        routing.localize_agent(agent, api_key=API_KEY)


def test_a_connected_client_answers_at_once(probe: dict[str, Any]) -> None:
    probe["client"] = FakeClient(connected=True)
    connect.require_holotab(API_KEY)
    assert probe["installs"] == 0 and probe["client"].waited == []
    assert probe["apps"] == [("Agents API", API_KEY)]


def test_a_holotab_that_connects_at_once_is_not_waited_for_aloud(
    probe: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    probe["client"] = FakeClient(arrives_after=0)
    with caplog.at_level("WARNING"):
        connect.require_holotab(API_KEY)
    assert probe["client"].waited == [connect.PROBE_WAIT_S]
    assert probe["installs"] == 1 and probe["client"].started == 1
    assert "Waiting" not in caplog.text


def test_the_wait_for_holotabs_retry_alarm_is_said_aloud(
    probe: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    probe["client"] = FakeClient(arrives_after=connect.FIRST_USE_WAIT_S)
    with caplog.at_level("WARNING"):
        connect.require_holotab(API_KEY)
    assert probe["client"].waited == [connect.PROBE_WAIT_S, connect.FIRST_USE_WAIT_S - connect.PROBE_WAIT_S]
    assert connect.FIRST_USE_WAIT_S == 65.0
    assert "Waiting up to 65s for HoloTab to connect" in caplog.text


def test_a_holotab_that_never_connects_names_the_setup_steps(probe: dict[str, Any]) -> None:
    with pytest.raises(RuntimeError, match="Connect to desktop apps"):
        connect.require_holotab(API_KEY)
    assert len(probe["client"].waited) == 2


def test_a_holotab_too_old_for_the_sdk_fails_without_the_long_wait(probe: dict[str, Any]) -> None:
    probe["client"].incompatible = TOO_OLD
    with pytest.raises(RuntimeError, match="update it from the Chrome Web Store"):
        connect.require_holotab(API_KEY)
    assert probe["client"].waited == [connect.PROBE_WAIT_S]


@pytest.mark.parametrize("error", [PermissionError("read-only home"), RuntimeError("unsafe socket path")])
def test_a_host_that_cannot_be_registered_fails_with_the_reason(probe: dict[str, Any], error: Exception) -> None:
    probe["install_error"] = error
    with pytest.raises(RuntimeError, match=str(error)):
        connect.require_holotab(API_KEY)
    assert probe["client"].waited == []


def test_the_wait_for_chrome_does_not_hold_the_lock(probe: dict[str, Any]) -> None:
    held: list[bool] = []
    holotab = probe["client"]
    holotab.wait_connected = lambda seconds: held.append(connect._lock.locked()) or False
    with pytest.raises(RuntimeError):
        connect.require_holotab(API_KEY)
    assert held == [False, False]


async def test_an_async_session_waits_for_holotab_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from hai_agents import AsyncClient
    from hai_agents.sessions.client import AsyncSessionsClient

    loop_thread = threading.current_thread()
    probed_on: list[threading.Thread] = []
    monkeypatch.setenv(AUTO_BRIDGE_ENV_VAR, "1")
    monkeypatch.setattr(routing, "require_holotab", lambda *_: probed_on.append(threading.current_thread()))
    monkeypatch.setattr(HoloTabBrowserBridge, "preflight", lambda self: None)
    monkeypatch.setattr("hai_agents_local.sessions.ensure_bridges", lambda bridges: [])
    monkeypatch.setattr("hai_agents_local.sessions._ensure_stop_watcher", lambda: None)

    async def create(self: Any, **kwargs: Any) -> Any:
        return types.SimpleNamespace(id=None)

    monkeypatch.setattr(AsyncSessionsClient, "create_session", create)
    async with AsyncClient(api_key=API_KEY) as client:
        await client.sessions.create_session(agent=HOLOTAB_AGENT, messages="hi")

    assert probed_on and loop_thread not in probed_on

from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
import time
from concurrent.futures import Future
from typing import Any

import httpx
import pytest

pytest.importorskip("hai_drivers.web.holotab.client")

from hai_drivers.web.holotab import client as client_module  # noqa: E402
from hai_drivers.web.holotab.client import CommandFailed, HoloTabRefused  # noqa: E402
from hai_drivers.web.interface import WebDriverInterface  # noqa: E402
from PIL import Image  # noqa: E402

from hai_agents_local import HoloTabBrowserBridge, LocalBridge  # noqa: E402
from hai_agents_local.holotab import bridge as bridge_module  # noqa: E402
from hai_agents_local.transport import CommandExchange  # noqa: E402

API_KEY = "hk-test"
WAIT_S = 5.0
DENIED_TEXT = "Agents API was denied in HoloTab"
REFUSED = "is not supported by HoloTab: it does not run JavaScript, or read or change cookies or local storage"


class FakeHoloTab:
    """Stands in for `HoloTabClient` and HoloTab behind it: records what the bridge asks, answers commands from
    ``answers``, and, like the real client, a stop or HoloTab's `STOPPED` ends the serve and the commands still waiting
    on that channel. With ``hold``, a command waits until its channel ends or ``release``."""

    def __init__(self, answers: dict[str, Any] | None = None, serves: bool = True, connected: bool = True) -> None:
        self.answers = answers or {}
        self.serves = serves
        self.connected = connected
        self.incompatible: str | None = None
        self.error = client_module.NOT_CONNECTED
        self.code: str | None = None
        self.started = 0
        self.served: list[dict[str, Any]] = []
        self.serving: set[str] = set()
        self.stopped: list[str] = []
        self.seen: list[str] = []
        self.args: dict[str, dict[str, Any]] = {}
        self.on_stopped: dict[str, Any] = {}
        self.answer: threading.Event | None = None
        self.awaiting: set[str] = set()
        self.withdrawn: set[str] = set()
        self.hold = False
        self.holding = threading.Event()
        self.pending: list[tuple[str, Future[str | None]]] = []

    def start(self) -> None:
        self.started += 1

    def wait_connected(self, seconds: float) -> bool:
        return self.connected

    def consent_pending(self, channel: str) -> bool:
        return channel in self.awaiting

    def serve(
        self,
        channel: str,
        label: str = "",
        start_url: str | None = None,
        upload_roots: Any = None,
        on_stopped: Any = None,
        timeout_s: float = client_module.SERVE_TIMEOUT_S,
    ) -> dict[str, Any]:
        if channel in self.awaiting:
            raise RuntimeError(f"Chrome channel {channel!r} is already awaiting an acknowledgement")
        self.served.append({"channel": channel, "label": label, "upload_roots": upload_roots, "timeout_s": timeout_s})
        self.withdrawn.discard(channel)
        if self.answer is not None:
            self.awaiting.add(channel)
            self.answer.wait(WAIT_S)
            self.awaiting.discard(channel)
        if channel in self.withdrawn:
            raise HoloTabRefused("the channel was stopped")
        if not self.serves:
            raise HoloTabRefused(self.error, self.code)
        self.serving.add(channel)
        if on_stopped is not None:
            self.on_stopped[channel] = on_stopped
        return {"type": "SERVING", "channel": channel}

    def execute(self, channel: str, name: str, args: dict[str, Any], timeout_s: float = 60.0) -> Any:
        if channel not in self.serving:
            raise CommandFailed(f"HoloTab is not serving {channel!r}")
        self.seen.append(name)
        self.args[name] = args
        if self.hold:
            ended: Future[str | None] = Future()
            self.pending.append((channel, ended))
            self.holding.set()
            reason = ended.result(timeout_s)
            if reason is not None:
                raise CommandFailed(reason)
        if name not in self.answers:
            raise CommandFailed(f"{name} failed in HoloTab")
        return self.answers[name]

    def stop(self, channel: str) -> None:
        self.stopped.append(channel)
        self.serving.discard(channel)
        self.on_stopped.pop(channel, None)
        self.fail(channel, "the channel was stopped")
        if channel in self.awaiting:
            self.withdrawn.add(channel)
            assert self.answer is not None
            self.answer.set()

    def holotab_stops(self, channel: str, reason: str) -> None:
        self.serving.discard(channel)
        self.fail(channel, f"HoloTab stopped the channel ({reason})")
        self.on_stopped.pop(channel)(reason)

    def fail(self, channel: str, reason: str | None) -> None:
        for waiting, ended in self.pending:
            if waiting == channel and not ended.done():
                ended.set_result(reason)

    def release(self) -> None:
        for channel, _ in self.pending:
            self.fail(channel, None)


def make(holotab: FakeHoloTab, **options: Any) -> tuple[HoloTabBrowserBridge, WebDriverInterface]:
    bridge = HoloTabBrowserBridge(api_key=API_KEY, holotab=holotab, **options)  # type: ignore[arg-type]
    driver = bridge.create_driver()
    bridge._driver = driver
    return bridge, driver


def dispatch(bridge: HoloTabBrowserBridge, name: str = "current_url") -> Any:
    """One command the way the bridge runs it: the result, or the error raised as a RuntimeError."""
    result, error = bridge._dispatch(name, {})
    if error is not None:
        raise RuntimeError(error)
    return result


async def serve(bridge: HoloTabBrowserBridge, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One command per poll; stops once every result has been posted."""
    batches = [[command] for command in commands]
    posts: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commands"):
            return httpx.Response(200, json=batches.pop(0))
        posts.append(json.loads(request.content))
        if not batches:
            bridge.request_stop()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await bridge._poll_loop(CommandExchange(client, "http://test"))
    return posts


def command(index: int, name: str, **args: Any) -> dict[str, Any]:
    return {"id": f"c{index}", "command_uid": f"u{index}", "name": name, "args": args}


def png_b64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


BUNDLE = {
    "screenshot_and_metadata": {
        "screenshot_b64": png_b64(),
        "metadata": {
            "title": "Inbox",
            "url": "https://mail.example.com/",
            "tabs": ["1"],
            "active_tab": "1",
            "screen_size": [1280, 800],
            "page_size": [1280, 800],
            "scroll_position": [0, 0],
            "mouse_position": [0, 0],
        },
    },
    "viewport_markdown": "",
}


def test_the_bridge_is_the_web_bridge_for_holotab_environments() -> None:
    assert issubclass(HoloTabBrowserBridge, LocalBridge)
    assert HoloTabBrowserBridge.environment_kind == "web"
    assert HoloTabBrowserBridge.environment == {"kind": "web", "host": "holotab"}
    assert HoloTabBrowserBridge(api_key=API_KEY, holotab=FakeHoloTab()).driver_interface() is WebDriverInterface  # type: ignore[arg-type]


def test_every_command_the_bridge_accepts_is_one_the_driver_runs() -> None:
    bridge, driver = make(FakeHoloTab())
    assert bridge.commands
    assert all(callable(getattr(type(driver), name, None)) for name in bridge.commands)


def test_nothing_opens_in_chrome_until_the_first_command() -> None:
    holotab = FakeHoloTab()
    bridge, _ = make(holotab)
    assert holotab.served == []
    bridge.close_channel()
    assert holotab.stopped == []


async def test_commands_run_in_the_users_chrome_through_holotab() -> None:
    holotab = FakeHoloTab(
        {"goto": None, "observation_bundle": BUNDLE, "click_at": None, "current_url": "https://mail.example.com/"}
    )
    bridge, driver = make(holotab, label=lambda: "Chat title")
    posts = await serve(
        bridge,
        [
            command(1, "goto", url="https://mail.example.com"),
            command(2, "observation_bundle", include_markdown=False),
            command(3, "click_at", x=10, y=20),
            command(4, "current_url"),
        ],
    )

    assert [post["error"] for post in posts] == [None] * 4
    assert posts[1]["result"]["screenshot_and_metadata"]["metadata"]["url"] == "https://mail.example.com/"
    assert posts[3]["result"] == "https://mail.example.com/"
    assert holotab.seen == ["goto", "observation_bundle", "click_at", "current_url"]
    assert holotab.args["click_at"]["x"] == 10
    [served] = holotab.served
    assert served["channel"] == bridge.session_id
    assert served["label"] == "Chat title"
    assert served["timeout_s"] == bridge_module.SERVE_TIMEOUT_S
    driver.destroy()


async def test_the_channel_opens_once_however_many_commands_follow() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab)
    await serve(bridge, [command(1, "current_url"), command(2, "current_url")])
    assert len(holotab.served) == 1
    driver.destroy()


def test_destroying_the_driver_stops_the_channel_without_asking_chrome() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab)
    dispatch(bridge)
    holotab.hold = True
    started = time.monotonic()
    driver.destroy()
    driver.destroy()
    assert time.monotonic() - started < 1
    assert holotab.seen == ["current_url"]
    assert holotab.stopped == [bridge.session_id]


@pytest.mark.parametrize("stop_on_refusal", [False, True])
async def test_a_refused_consent_answers_every_later_command_at_once_and_the_chrome_stays_closed(
    stop_on_refusal: bool,
) -> None:
    asked: list[int] = []
    holotab = FakeHoloTab({"goto": None})
    bridge, _ = make(holotab, consent=lambda: asked.append(1) or False, stop_on_refusal=stop_on_refusal)
    posts = await serve(
        bridge, [command(1, "goto", url="https://example.com"), command(2, "goto", url="https://x.com")]
    )

    refusal = "the user did not allow the agent to use their Chrome"
    assert [post["error"] for post in posts] == [refusal] if stop_on_refusal else [refusal, refusal]
    assert bridge.refusal == refusal
    assert asked == [1]
    assert holotab.served == []
    bridge.close_channel()
    assert holotab.stopped == []


async def test_a_granted_consent_is_asked_once_before_the_first_command() -> None:
    asked: list[int] = []
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab, consent=lambda: asked.append(1) or True)
    posts = await serve(bridge, [command(1, "current_url"), command(2, "current_url")])
    assert [post["error"] for post in posts] == [None, None]
    assert asked == [1]
    driver.destroy()


async def test_a_holotab_that_does_not_serve_says_why() -> None:
    holotab = FakeHoloTab(serves=False)
    bridge, driver = make(holotab)
    [post] = await serve(bridge, [command(1, "current_url")])
    assert post["error"] == client_module.NOT_CONNECTED
    driver.destroy()


async def test_a_holotab_that_is_not_connected_names_the_two_setup_steps_and_serves_nothing() -> None:
    holotab = FakeHoloTab(connected=False)
    bridge, driver = make(holotab)
    [post] = await serve(bridge, [command(1, "current_url")])
    assert "Install the HoloTab extension" in post["error"]
    assert '"Connect to desktop apps"' in post["error"]
    assert holotab.served == []
    driver.destroy()


def test_a_failed_start_is_retried_by_the_next_command() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"}, serves=False)
    bridge, _ = make(holotab)
    with pytest.raises(RuntimeError, match="not connected"):
        dispatch(bridge)

    holotab.serves = True
    assert dispatch(bridge) == "https://example.com"
    assert len(holotab.served) == 2
    bridge.close_channel()
    assert holotab.stopped == [bridge.session_id]


async def test_a_new_session_on_the_same_bridge_works_after_an_earlier_failure() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"}, connected=False)
    bridge, driver = make(holotab)
    [failed] = await serve(bridge, [command(1, "current_url")])
    assert failed["error"]

    holotab.connected = True
    bridge._stop_event = asyncio.Event()
    [post] = await serve(bridge, [command(2, "current_url")])
    assert post["error"] is None
    assert post["result"] == "https://example.com"
    driver.destroy()


async def test_a_destroyed_driver_is_replaced_while_the_bridge_is_not_stopping() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab)
    driver.destroy()
    [post] = await serve(bridge, [command(1, "current_url")])
    assert post["error"] is None
    assert bridge._driver is not driver
    bridge._driver.destroy()  # type: ignore[union-attr]


def test_closing_the_bridge_stops_the_channel_and_the_next_command_opens_it_again() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, _ = make(holotab)
    dispatch(bridge)
    bridge.close_channel()
    assert holotab.stopped == [bridge.session_id]

    assert dispatch(bridge) == "https://example.com"
    assert len(holotab.served) == 2


def test_the_preflight_starts_the_holotab_client() -> None:
    holotab = FakeHoloTab()
    HoloTabBrowserBridge(api_key=API_KEY, holotab=holotab).preflight()  # type: ignore[arg-type]
    assert holotab.started == 1


def test_bridges_share_one_process_client_per_app_name_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[tuple[str, str]] = []
    registered: list[tuple] = []

    class RecordingClient:
        def __init__(self, name: str, key: str) -> None:
            created.append((name, key))

    monkeypatch.setattr(bridge_module, "_process_clients", {})
    monkeypatch.setattr(client_module, "HoloTabClient", RecordingClient)
    monkeypatch.setattr(bridge_module.atexit, "register", lambda *call: registered.append(call))

    first = HoloTabBrowserBridge(api_key=lambda: "hk-one").holotab_client()
    again = HoloTabBrowserBridge(api_key="hk-one").holotab_client()
    other = HoloTabBrowserBridge(api_key="hk-one", client="Custom app").holotab_client()

    assert first is again and other is not first
    assert created == [("Agents API", "hk-one"), ("Custom app", "hk-one")]
    assert [args for _, *args in registered] == [[first], [other]]


async def test_the_tab_group_is_named_after_the_client_by_default() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab, client="Custom app")
    await serve(bridge, [command(1, "current_url")])
    assert [served["label"] for served in holotab.served] == ["Custom app"]
    driver.destroy()


async def test_an_explicit_label_wins_over_the_client_name() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab, client="Custom app", label="My group")
    await serve(bridge, [command(1, "current_url")])
    assert [served["label"] for served in holotab.served] == ["My group"]
    driver.destroy()


def test_at_exit_the_bridges_stop_their_channels_before_the_client_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(bridge_module, "stop_bridges", lambda: order.append("bridges stopped"))
    bridge_module._close_at_exit(type("Client", (), {"close": lambda self: order.append("client closed")})())
    assert order == ["bridges stopped", "client closed"]


def test_at_exit_a_bridge_that_does_not_stop_in_time_still_lets_the_client_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    def stuck() -> None:
        raise TimeoutError("Could not confirm stop of local web bridge")

    monkeypatch.setattr(bridge_module, "stop_bridges", stuck)
    bridge_module._close_at_exit(type("Client", (), {"close": lambda self: closed.append(True)})())
    assert closed == [True]


async def test_after_holotab_denied_the_app_every_later_command_gets_its_words_at_once_without_a_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holotab = FakeHoloTab(serves=False)
    holotab.error, holotab.code = DENIED_TEXT, "DENIED"
    bridge, driver = make(holotab)
    started = time.monotonic()
    posts = await serve(bridge, [command(index, "current_url") for index in range(4)])

    assert [post["error"] for post in posts] == [DENIED_TEXT] * 4
    assert len(holotab.served) == 1
    assert time.monotonic() - started < WAIT_S

    async def served_until_stopped(self: LocalBridge) -> None:
        return None

    monkeypatch.setattr(LocalBridge, "run", served_until_stopped)
    await bridge.run()
    driver.destroy()


async def test_with_stop_on_refusal_holotabs_denial_ends_the_session_and_run_raises_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holotab = FakeHoloTab(serves=False)
    holotab.error, holotab.code = DENIED_TEXT, "DENIED"
    bridge, driver = make(holotab, stop_on_refusal=True)
    posts = await serve(bridge, [command(1, "current_url"), command(2, "current_url")])
    assert [post["error"] for post in posts] == [DENIED_TEXT]
    assert bridge.refusal == DENIED_TEXT
    assert bridge._stop_event.is_set()

    async def served_until_stopped(self: LocalBridge) -> None:
        return None

    monkeypatch.setattr(LocalBridge, "run", served_until_stopped)
    with pytest.raises(PermissionError, match="denied in HoloTab"):
        await bridge.run()
    driver.destroy()


async def test_a_consent_that_timed_out_fails_the_command_but_keeps_the_session() -> None:
    holotab = FakeHoloTab(serves=False)
    holotab.error, holotab.code = "Agents API was not allowed in time", "CONSENT_TIMEOUT"
    bridge, driver = make(holotab)
    [post] = await serve(bridge, [command(1, "current_url")])
    assert post["error"] == "Agents API was not allowed in time"
    assert bridge.refusal is None
    driver.destroy()


def test_when_holotab_stops_the_channel_on_its_own_the_waiting_and_later_commands_fail_at_once() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab)
    assert dispatch(bridge) == "https://example.com"
    holotab.hold = True
    failures: list[str] = []

    def waiting() -> None:
        try:
            driver.current_url()
        except Exception as exc:
            failures.append(str(exc))

    worker = threading.Thread(target=waiting)
    worker.start()
    assert holotab.holding.wait(WAIT_S)
    started = time.monotonic()
    holotab.holotab_stops(bridge.session_id, "closed")
    worker.join(WAIT_S)
    with pytest.raises(RuntimeError, match=r"HoloTab stopped the channel \(closed\)"):
        driver.current_url()
    assert failures == ["HoloTab stopped the channel (closed)"]
    assert time.monotonic() - started < 1
    assert len(holotab.served) == 1
    driver.destroy()


async def test_a_stop_while_a_command_waits_on_chrome_stops_the_channel_and_frees_the_command() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, _ = make(holotab)
    assert dispatch(bridge) == "https://example.com"
    holotab.hold = True
    waiting = asyncio.create_task(asyncio.to_thread(bridge._dispatch, "current_url", {}))
    assert await asyncio.to_thread(holotab.holding.wait, WAIT_S)
    started = time.monotonic()
    await bridge.interrupt_driver()
    _, error = await asyncio.wait_for(waiting, WAIT_S)
    assert error == "the channel was stopped"
    assert time.monotonic() - started < 1
    assert holotab.stopped == [bridge.session_id]


async def test_the_upload_roots_reach_holotab_with_the_serve() -> None:
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, driver = make(holotab, upload_roots=["/srv/uploads"])
    await serve(bridge, [command(1, "current_url")])
    assert [served["upload_roots"] for served in holotab.served] == [["/srv/uploads"]]
    driver.destroy()


async def test_a_holotab_too_old_for_the_sdk_is_named_instead_of_the_setup_steps() -> None:
    holotab = FakeHoloTab(connected=False)
    holotab.incompatible = client_module.TOO_OLD
    bridge, driver = make(holotab)
    [post] = await serve(bridge, [command(1, "current_url")])
    assert post["error"] == client_module.TOO_OLD
    driver.destroy()


def waiting_for(client: str = "Agents API") -> str:
    return f"Waiting for the user to allow {client} in HoloTab's side panel: run the same action again in a moment"


def test_a_command_waiting_on_holotabs_consent_fails_well_before_the_agents_limit() -> None:
    assert bridge_module.OPEN_HOLD_S + 10 < bridge_module.SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S


def test_while_the_user_has_not_answered_commands_are_told_to_retry_and_the_next_one_uses_the_allowed_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "OPEN_HOLD_S", 0.2)
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    holotab.answer = threading.Event()
    bridge, _ = make(holotab)

    for _ in range(2):
        started = time.monotonic()
        with pytest.raises(RuntimeError) as waiting:
            dispatch(bridge)
        assert str(waiting.value) == waiting_for()
        assert time.monotonic() - started < 2
    holotab.answer.set()

    assert dispatch(bridge) == "https://example.com"
    assert len(holotab.served) == 1
    bridge.close_channel()
    assert holotab.stopped == [bridge.session_id]


def test_a_denial_after_the_wait_reaches_the_next_command_and_every_later_one_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "OPEN_HOLD_S", 1.0)
    holotab = FakeHoloTab(serves=False)
    holotab.error, holotab.code = DENIED_TEXT, "DENIED"
    holotab.answer = threading.Event()
    bridge, _ = make(holotab)

    with pytest.raises(RuntimeError, match="Waiting for the user to allow"):
        dispatch(bridge)
    holotab.answer.set()
    for _ in range(3):
        started = time.monotonic()
        with pytest.raises(RuntimeError, match=DENIED_TEXT):
            dispatch(bridge)
        assert time.monotonic() - started < 2
    assert len(holotab.served) == 1
    bridge.close_channel()
    assert holotab.stopped == []


def test_closing_while_the_user_has_not_answered_withdraws_the_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge_module, "OPEN_HOLD_S", 0.2)
    holotab = FakeHoloTab({"current_url": "https://example.com"})
    holotab.answer = threading.Event()
    bridge, _ = make(holotab)
    with pytest.raises(RuntimeError, match="Waiting for the user to allow"):
        dispatch(bridge)

    bridge.close_channel()

    assert holotab.stopped == [bridge.session_id]
    deadline = time.monotonic() + WAIT_S
    while holotab.awaiting and time.monotonic() < deadline:
        time.sleep(0.01)
    assert holotab.serving == set()


def test_a_bridge_closed_while_the_user_is_asked_for_consent_never_serves_its_session() -> None:
    asked, answer = threading.Event(), threading.Event()

    def consent() -> bool:
        asked.set()
        answer.wait(WAIT_S)
        return True

    holotab = FakeHoloTab({"current_url": "https://example.com"})
    bridge, _ = make(holotab, consent=consent)
    failures: list[str] = []

    def first_command() -> None:
        try:
            dispatch(bridge)
        except RuntimeError as exc:
            failures.append(str(exc))

    worker = threading.Thread(target=first_command)
    worker.start()
    assert asked.wait(WAIT_S)
    bridge.close_channel()
    answer.set()
    worker.join(WAIT_S)

    assert failures == ["the Chrome driver was destroyed"]
    assert holotab.served == []


def test_a_bridge_closed_while_its_serve_is_on_the_way_stops_the_channel_once_served() -> None:
    order: list[str] = []

    class StoppedOnTheWay(FakeHoloTab):
        def serve(self, channel: str, **options: Any) -> Any:
            bridge.close_channel()
            served = super().serve(channel, **options)
            order.append("served")
            return served

        def stop(self, channel: str) -> None:
            order.append("stop")
            super().stop(channel)

    holotab = StoppedOnTheWay({"current_url": "https://example.com"})
    bridge, _ = make(holotab)

    with pytest.raises(RuntimeError, match="the Chrome driver was destroyed"):
        dispatch(bridge)

    assert order == ["stop", "served", "stop"]
    assert holotab.stopped == [bridge.session_id, bridge.session_id]
    assert holotab.serving == set()


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("supports_files", {}),
        ("upload_file", {"path": "/a", "x": 1, "y": 2}),
        ("get_cookies", {}),
        ("add_cookies", {"cookies": []}),
        ("delete_cookies", {}),
        ("get_local_storage", {}),
        ("set_local_storage", {"local_storage": {}}),
        ("execute_script", {"script": "return document.cookie"}),
    ],
)
def test_a_command_that_never_reaches_chrome_opens_nothing(name: str, args: dict[str, Any]) -> None:
    holotab = FakeHoloTab()
    bridge, driver = make(holotab)
    _, error = bridge._dispatch(name, args)
    if name in bridge_module.NOT_SUPPORTED:
        assert error is not None and error.endswith(REFUSED)
    assert holotab.served == [] and holotab.seen == []
    driver.destroy()


def test_without_hai_drivers_holotab_the_install_hint_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def without_holotab(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("hai_drivers.web.holotab"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_holotab)
    bridge = HoloTabBrowserBridge(api_key=API_KEY)
    with pytest.raises(ImportError, match=r"hai-agents\[holotab\]"):
        bridge.create_driver()
    with pytest.raises(ImportError, match=r"hai-agents\[holotab\]"):
        bridge.holotab_client()

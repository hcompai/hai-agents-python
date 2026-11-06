from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any

import httpx
import pytest

pytest.importorskip("hai_drivers.web.interface")

from hai_drivers.web.interface import WebDriverInterface  # noqa: E402
from PIL import Image  # noqa: E402

from hai_agents_local import HoloTabBrowserBridge, LocalBridge  # noqa: E402
from hai_agents_local.holotab import link as link_module  # noqa: E402
from hai_agents_local.holotab.commands import LocalCommandServer  # noqa: E402
from hai_agents_local.holotab.driver import LocalChromeDriver  # noqa: E402
from hai_agents_local.transport import CommandExchange  # noqa: E402

from .holotab_fake_extension import FakeExtension  # noqa: E402

API_KEY = "test-key"


class FakeLink:
    """Stands in for the link: records what the bridge asks of the extension, and starts the fake extension on serve."""

    def __init__(
        self, extension_answers: dict[str, object] | None = None, serves: bool = True, connected: bool = True
    ) -> None:
        self.answers = extension_answers or {}
        self.serves = serves
        self.connected = connected
        self.started = 0
        self.served: list[dict[str, Any]] = []
        self.stopped: list[str] = []
        self.last_error: str | None = "Chrome is not connected through the HoloTab extension"
        self.extension: FakeExtension | None = None
        self.server: LocalCommandServer | None = None

    def start(self) -> None:
        self.started += 1

    def wait_connected(self, seconds: float) -> bool:
        return self.connected

    def serve(
        self,
        channel: str,
        base_url: str,
        api_key: str,
        start_url: str | None = None,
        label: str = "",
        client: str | None = None,
    ) -> Any:
        self.served.append(
            {"channel": channel, "base_url": base_url, "api_key": api_key, "label": label, "client": client}
        )
        if not self.serves:
            return None
        assert self.server is not None
        self.extension = FakeExtension(self.server, self.answers)
        self.extension.__enter__()
        return {"type": "SERVING", "channel": channel}

    def stop(self, channel: str) -> None:
        self.stopped.append(channel)
        if self.extension is not None:
            self.extension.__exit__()


def make(link: FakeLink, **options: Any) -> tuple[HoloTabBrowserBridge, LocalChromeDriver]:
    bridge = HoloTabBrowserBridge(api_key=API_KEY, link=link, **options)  # type: ignore[arg-type]
    driver = bridge.create_driver()
    link.server = driver._server
    bridge._driver = driver
    return bridge, driver


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


def test_the_bridge_is_the_web_bridge_for_the_users_device() -> None:
    assert issubclass(HoloTabBrowserBridge, LocalBridge)
    assert HoloTabBrowserBridge.environment_kind == "web"
    assert HoloTabBrowserBridge.environment == {"kind": "web", "host": "user_device"}
    assert HoloTabBrowserBridge(api_key=API_KEY, link=FakeLink()).driver_interface() is WebDriverInterface  # type: ignore[arg-type]


def test_every_command_the_bridge_accepts_is_one_the_driver_runs() -> None:
    bridge = HoloTabBrowserBridge(api_key=API_KEY, link=FakeLink())  # type: ignore[arg-type]
    assert bridge.commands
    assert all(callable(getattr(LocalChromeDriver, name, None)) for name in bridge.commands)


def test_nothing_opens_in_chrome_until_the_first_command() -> None:
    link = FakeLink()
    _, driver = make(link)
    assert link.served == []
    with pytest.raises(RuntimeError, match="not running"):
        _ = driver._server.base_url
    driver.destroy()
    assert link.stopped == []


async def test_commands_run_in_the_users_chrome_through_the_extension() -> None:
    link = FakeLink(
        {"goto": None, "observation_bundle": BUNDLE, "click_at": None, "execute_script": {"title": "Inbox"}}
    )
    bridge, driver = make(link, label=lambda: "Chat title")
    posts = await serve(
        bridge,
        [
            command(1, "goto", url="https://mail.example.com"),
            command(2, "observation_bundle", include_markdown=False),
            command(3, "click_at", x=10, y=20),
            command(4, "execute_script", script="return {title: document.title}"),
        ],
    )

    assert [post["error"] for post in posts] == [None] * 4
    assert posts[1]["result"]["screenshot_and_metadata"]["metadata"]["url"] == "https://mail.example.com/"
    assert posts[3]["result"] == {"title": "Inbox"}
    assert link.extension is not None
    assert link.extension.seen == ["goto", "observation_bundle", "click_at", "execute_script"]
    assert link.extension.args["click_at"]["x"] == 10
    [served] = link.served
    assert served["channel"] == bridge.session_id
    assert served["label"] == "Chat title"
    assert served["client"] == "Agents API"
    assert served["api_key"] == driver._server.token
    assert served["base_url"].startswith("http://127.0.0.1:")
    driver.destroy()


async def test_the_channel_opens_once_however_many_commands_follow() -> None:
    link = FakeLink({"current_url": "https://example.com"})
    bridge, driver = make(link)
    await serve(bridge, [command(1, "current_url"), command(2, "current_url")])
    assert len(link.served) == 1
    driver.destroy()


async def test_a_refused_consent_is_an_error_result_and_the_chrome_stays_closed() -> None:
    asked: list[int] = []
    link = FakeLink({"goto": None})
    bridge, driver = make(link, consent=lambda: asked.append(1) or False)
    posts = await serve(
        bridge, [command(1, "goto", url="https://example.com"), command(2, "goto", url="https://x.com")]
    )

    assert all("did not allow" in post["error"] for post in posts)
    assert asked == [1]
    assert link.served == []
    driver.destroy()
    assert link.stopped == []


async def test_a_granted_consent_is_asked_once_before_the_first_command() -> None:
    asked: list[int] = []
    link = FakeLink({"current_url": "https://example.com"})
    bridge, driver = make(link, consent=lambda: asked.append(1) or True)
    posts = await serve(bridge, [command(1, "current_url"), command(2, "current_url")])
    assert [post["error"] for post in posts] == [None, None]
    assert asked == [1]
    driver.destroy()


async def test_a_link_that_does_not_serve_says_why() -> None:
    link = FakeLink(serves=False)
    bridge, driver = make(link)
    [post] = await serve(bridge, [command(1, "current_url")])
    assert post["error"] == "Chrome is not connected through the HoloTab extension"
    driver.destroy()


async def test_a_link_that_is_not_connected_names_the_two_setup_steps_and_leaves_nothing_running() -> None:
    link = FakeLink(connected=False)
    bridge, driver = make(link)
    [post] = await serve(bridge, [command(1, "current_url")])
    assert "Install the HoloTab extension" in post["error"]
    assert '"Connect to desktop apps"' in post["error"]
    assert link.served == []
    with pytest.raises(RuntimeError, match="not running"):
        _ = driver._server.base_url
    driver.destroy()


def test_a_failed_start_is_retried_by_the_next_command() -> None:
    link = FakeLink({"current_url": "https://example.com"}, serves=False)
    _, driver = make(link)
    with pytest.raises(RuntimeError, match="not connected"):
        driver.current_url()
    assert not driver.destroyed

    link.serves = True
    assert driver.current_url() == "https://example.com"
    assert len(link.served) == 2
    driver.destroy()
    assert link.stopped == [link.served[0]["channel"]]


async def test_a_new_session_on_the_same_bridge_works_after_an_earlier_failure() -> None:
    link = FakeLink({"current_url": "https://example.com"}, connected=False)
    bridge, driver = make(link)
    [failed] = await serve(bridge, [command(1, "current_url")])
    assert failed["error"]

    link.connected = True
    bridge._stop_event = asyncio.Event()
    [post] = await serve(bridge, [command(2, "current_url")])
    assert post["error"] is None
    assert post["result"] == "https://example.com"
    driver.destroy()


async def test_a_destroyed_driver_is_replaced_while_the_bridge_is_not_stopping() -> None:
    link = FakeLink({"current_url": "https://example.com"})
    bridge, driver = make(link)
    driver.destroy()
    create = bridge.create_driver

    def create_and_track() -> LocalChromeDriver:
        fresh = create()
        link.server = fresh._server
        return fresh

    bridge.create_driver = create_and_track  # type: ignore[method-assign]
    [post] = await serve(bridge, [command(1, "current_url")])
    assert post["error"] is None
    assert bridge._driver is not driver
    bridge._driver.destroy()  # type: ignore[union-attr]


def test_destroying_the_bridge_stops_the_channel_and_the_server() -> None:
    link = FakeLink({"current_url": "https://example.com"})
    bridge, driver = make(link)
    driver.current_url()
    driver.destroy()

    assert link.stopped == [bridge.session_id]
    with pytest.raises(RuntimeError, match="not running"):
        _ = driver._server.base_url


def test_the_preflight_starts_listening_for_the_extension() -> None:
    link = FakeLink()
    HoloTabBrowserBridge(api_key=API_KEY, link=link).preflight()  # type: ignore[arg-type]
    assert link.started == 1


async def test_the_client_name_the_bridge_was_given_is_the_one_served() -> None:
    link = FakeLink({"current_url": "https://example.com"})
    bridge, driver = make(link, client="Custom app")
    await serve(bridge, [command(1, "current_url")])
    assert [served["client"] for served in link.served] == ["Custom app"]
    driver.destroy()


async def test_the_tab_group_is_named_after_the_client_by_default() -> None:
    link = FakeLink({"current_url": "https://example.com"})
    bridge, driver = make(link, client="Custom app")
    await serve(bridge, [command(1, "current_url")])
    assert [served["label"] for served in link.served] == ["Custom app"]
    driver.destroy()


async def test_an_explicit_label_wins_over_the_client_name() -> None:
    link = FakeLink({"current_url": "https://example.com"})
    bridge, driver = make(link, client="Custom app", label="My group")
    await serve(bridge, [command(1, "current_url")])
    assert [served["label"] for served in link.served] == ["My group"]
    driver.destroy()


def test_at_exit_the_bridges_stop_their_channels_before_the_link_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    registered: list[tuple] = []

    class ClosingLink:
        def close(self) -> None:
            order.append("link closed")

    monkeypatch.setattr(link_module, "_process_link", None)
    monkeypatch.setattr(link_module, "HoloTabLink", ClosingLink)
    monkeypatch.setattr(link_module.atexit, "register", lambda *call: registered.append(call))
    monkeypatch.setattr(link_module, "stop_bridges", lambda: order.append("bridges stopped"))

    shared = link_module.process_link()
    [(handler, *args)] = registered
    handler(*args)

    assert args == [shared]
    assert order == ["bridges stopped", "link closed"]


def test_at_exit_a_bridge_that_does_not_stop_in_time_still_lets_the_link_close(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    def stuck() -> None:
        raise TimeoutError("Could not confirm stop of local web bridge")

    monkeypatch.setattr(link_module, "stop_bridges", stuck)
    link_module._close_at_exit(type("ClosingLink", (), {"close": lambda self: closed.append(True)})())
    assert closed == [True]

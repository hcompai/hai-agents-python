from __future__ import annotations

import base64
import inspect
import io
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("hai_drivers.web.interface")

from hai_drivers.web.interface import WebDriverInterface  # noqa: E402
from PIL import Image  # noqa: E402

from hai_agents_local.holotab.commands import LocalCommandServer  # noqa: E402
from hai_agents_local.holotab.driver import EXECUTOR_RUNS, EXTENSION_NATIVE, LocalChromeDriver  # noqa: E402

from .holotab_fake_extension import FakeExtension  # noqa: E402

WAIT_S = 10.0


@pytest.fixture
def server() -> Iterator[LocalCommandServer]:
    running = LocalCommandServer()
    running.start()
    yield running
    running.stop()


def test_a_command_goes_out_and_its_result_comes_back(server: LocalCommandServer) -> None:
    with FakeExtension(server, {"goto": None, "current_url": "https://example.com"}):
        assert LocalChromeDriver(server, timeout_s=WAIT_S).current_url() == "https://example.com"


def test_every_abstract_method_is_implemented() -> None:
    assert LocalChromeDriver.__abstractmethods__ == frozenset()
    for name in WebDriverInterface.__abstractmethods__ - {"destroy"}:
        assert getattr(LocalChromeDriver, name) is not getattr(WebDriverInterface, name)


def test_the_signature_the_model_sees_is_the_interface_signature() -> None:
    assert list(inspect.signature(LocalChromeDriver.goto).parameters) == ["self", "url"]


def test_javascript_runs_in_the_page(server: LocalCommandServer) -> None:
    with FakeExtension(server, {"execute_script": {"title": "Q3 Report"}}) as extension:
        result = LocalChromeDriver(server, timeout_s=WAIT_S).execute_script("return {title: document.title}")

    assert result == {"title": "Q3 Report"}
    assert "execute_script" in extension.seen


def test_a_concrete_helper_composes_on_the_generated_ones(server: LocalCommandServer) -> None:
    with FakeExtension(server, {"get_viewport_html": "<h1>Q3</h1><p>Revenue rose.</p>"}):
        assert LocalChromeDriver(server, timeout_s=WAIT_S).viewport_markdown() == "# Q3\n\nRevenue rose."


def test_a_page_error_raises_rather_than_returning_a_string(server: LocalCommandServer) -> None:
    with FakeExtension(server, {}), pytest.raises(RuntimeError, match="not supported"):
        LocalChromeDriver(server, timeout_s=WAIT_S).get_tabs()


def test_the_opener_runs_once_before_the_first_command_and_the_closer_once_on_destroy(
    server: LocalCommandServer,
) -> None:
    events: list[str] = []
    driver = LocalChromeDriver(
        server,
        timeout_s=WAIT_S,
        opener=lambda: events.append("open"),
        closer=lambda: events.append("close"),
    )
    assert events == []
    with FakeExtension(server, {"current_url": "https://example.com"}):
        driver.current_url()
        driver.current_url()
    driver.destroy()
    assert events == ["open", "close"]


def test_a_driver_that_never_opened_has_nothing_to_close(server: LocalCommandServer) -> None:
    events: list[str] = []
    LocalChromeDriver(server, opener=lambda: events.append("open"), closer=lambda: events.append("close")).destroy()
    assert events == []
    with pytest.raises(RuntimeError, match="not running"):
        _ = server.base_url


class ExtensionLike(LocalCommandServer):
    """Answers like the extension: JSON over HTTP, so bytes arrive as base64 text."""

    def __init__(self, png_b64: str) -> None:
        super().__init__()
        self.asked: list[str] = []
        self._png = png_b64

    def submit(self, name: str, args: dict[str, Any] | None = None, timeout_s: float = WAIT_S) -> Any:
        self.asked.append(name)
        metadata = {
            "title": "Workshop",
            "url": "https://example.com/workshop",
            "tabs": ["1"],
            "active_tab": "1",
            "screen_size": [1280, 800],
            "page_size": [1280, 800],
            "scroll_position": [0, 0],
            "mouse_position": [0, 0],
        }
        if name == "observation_bundle":
            return {
                "screenshot_and_metadata": {"screenshot_b64": self._png, "metadata": metadata},
                "viewport_markdown": "",
            }
        if name == "screenshot_png_bytes":
            return self._png
        raise AssertionError(f"unexpected command {name}")


def png_b64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_an_observation_of_the_users_chrome_is_one_extension_command_that_builds() -> None:
    extension = ExtensionLike(png_b64())
    bundle = LocalChromeDriver(extension).observation_bundle(include_markdown=False)

    assert extension.asked == ["observation_bundle"]
    assert bundle.screenshot_and_metadata.metadata.url == "https://example.com/workshop"


def test_the_commands_the_extension_answers_in_one_round_trip_are_never_composed_upstream() -> None:
    assert {"observation_bundle", "screenshot_and_metadata", "webpage_metadata"} == EXTENSION_NATIVE
    for name in EXTENSION_NATIVE:
        assert getattr(LocalChromeDriver, name) is not getattr(WebDriverInterface, name)


def test_bytes_the_interface_promises_arrive_as_bytes_not_the_wire_text() -> None:
    png = png_b64()
    driver = LocalChromeDriver(ExtensionLike(png))

    assert driver.screenshot_png_bytes() == base64.b64decode(png)
    assert driver.screenshot_png_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_viewport_read_is_one_extension_command_not_the_interface_default(server: LocalCommandServer) -> None:
    for name in EXECUTOR_RUNS | EXTENSION_NATIVE:
        assert getattr(LocalChromeDriver, name) is not getattr(WebDriverInterface, name)
    with FakeExtension(server, {"get_viewport_html": "<p>Q3</p>"}) as extension:
        assert LocalChromeDriver(server, timeout_s=WAIT_S).get_viewport_html() == "<p>Q3</p>"
    assert extension.seen == ["get_viewport_html"]

"""Local web bridge: the agent's browser tools run in the user's own Chrome through the HoloTab extension."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..bridge import LocalBridge, TokenSource
from ..transport import Json
from .commands import LocalCommandServer
from .link import HoloTabLink, process_link

if TYPE_CHECKING:
    from .driver import LocalChromeDriver

logger = logging.getLogger(__name__)

DEFAULT_CLIENT = "Agents API"
CONNECT_WAIT_S = 2.0
NOT_CONNECTED = (
    "Chrome is not connected through HoloTab. Install the HoloTab extension in Chrome, "
    'then turn on "Connect to desktop apps" in its settings.'
)


class HoloTabBrowserBridge(LocalBridge["LocalChromeDriver"]):
    """Serves web environments with the user's signed-in Chrome, driven by the HoloTab extension.

    Nothing opens in Chrome until the agent's first command: then the extension is asked, through the link, to poll a
    loopback command server for this session, and ``destroy`` stops that channel; its tabs stay open for the user to close.
    """

    environment_kind = "web"
    environment = {"kind": "web", "host": "user_device"}
    startup_hint = "HoloTab must be installed in Chrome with `Connect to desktop apps` turned on"

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
        link: HoloTabLink | None = None,
        label: str | Callable[[], str] | None = None,
        client: str = DEFAULT_CLIENT,
        consent: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.link = link or process_link()
        self.label = label
        self.client = client
        self.consent = consent
        self._allowed: bool | None = None

    def preflight(self) -> None:
        """Start listening, so the extension's native host finds the link while the bridge waits for its first command."""
        self.link.start()

    def create_driver(self) -> LocalChromeDriver:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[browser].
        try:
            from .driver import LocalChromeDriver
        except ImportError as exc:
            raise ImportError(
                "Local browser control requires extra deps. Install with: pip install 'hai-agents[browser]'"
            ) from exc
        server = LocalCommandServer(self.session_id)
        return LocalChromeDriver(server, opener=lambda: self._open(server), closer=self._close)

    def driver_interface(self) -> type:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[browser].
        from hai_drivers.web.interface import WebDriverInterface

        return WebDriverInterface

    def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[Json, str | None]:
        driver = self._driver
        if driver is not None and driver.destroyed and not self._stop_event.is_set():
            self._driver = self.create_driver()
        return super()._dispatch(name, args)

    def _open(self, server: LocalCommandServer) -> None:
        """Starts serving this session in Chrome. A failure leaves nothing running, so the next command retries."""
        if not self._consented():
            raise PermissionError("the user did not allow the agent to use their Chrome")
        try:
            self.link.start()
            if not self.link.wait_connected(CONNECT_WAIT_S):
                raise RuntimeError(NOT_CONNECTED)
            base_url = server.start()
            label = self.label() if callable(self.label) else self.label or self.client
            if self.link.serve(self.session_id, base_url, server.token, label=label, client=self.client) is None:
                raise RuntimeError(self.link.last_error or "HoloTab did not serve the Chrome channel")
        except BaseException:
            server.stop()
            raise

    def _consented(self) -> bool:
        if self.consent is None:
            return True
        if self._allowed is None:
            self._allowed = bool(self.consent())
        return self._allowed

    def _close(self) -> None:
        self.link.stop(self.session_id)

"""Local web bridge: the agent's browser tools run in the user's own Chrome through the HoloTab extension."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, InvalidStateError, wait
from typing import TYPE_CHECKING, Any

from ..bridge import TokenSource, resolve_token
from ..browser import WebBridge
from ..manager import stop_bridges
from ..transport import CommandExchange, Json

if TYPE_CHECKING:
    from hai_drivers.web.holotab.client import HoloTabClient
    from hai_drivers.web.interface import WebDriverInterface

logger = logging.getLogger(__name__)

DEFAULT_CLIENT = "Agents API"
CONNECT_WAIT_S = 2.0
SERVE_TIMEOUT_S = 12.0
OPEN_HOLD_S = CONNECT_WAIT_S + SERVE_TIMEOUT_S + 6.0
SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S = 60.0
COMMAND_TIMEOUT_S = SAGENT_USER_DEVICE_COMMAND_TIMEOUT_S - 10.0
MIN_COMMAND_WAIT_S = 1.0
NOT_CONNECTED = (
    "Chrome is not connected through HoloTab. Install the HoloTab extension in Chrome, "
    'then turn on "Connect to desktop apps" in its settings.'
)
INSTALL_HINT = "HoloTab control requires extra deps. Install with: pip install 'hai-agents[holotab]'"
DESTROYED = "the Chrome driver was destroyed"
NOT_SUPPORTED = frozenset(
    {"add_cookies", "delete_cookies", "execute_script", "get_cookies", "get_local_storage", "set_local_storage"}
)


class HoloTabBrowserBridge(WebBridge["WebDriverInterface"]):
    """Serves web environments with the user's signed-in Chrome, driven by the HoloTab extension.

    Nothing opens in Chrome until the agent's first command: then HoloTab is asked, through the ``holotab`` client
    (by default one per app name and key, shared by the process), to serve a tab group for this session, and a stop
    ends that channel without waiting for Chrome; its tabs stay open for the user to close. A failed open fails that
    command only; the next one opens again.

    While the user has not yet answered HoloTab's side panel, a command waits at most ``OPEN_HOLD_S``, well under the
    agent's command limit, then fails with a message to run it again; the serve keeps waiting for the answer in the
    background, and the next command uses the channel once allowed. After a refusal, by ``consent`` or by the user in
    HoloTab, every command fails at once with the reason and nothing opens; with ``stop_on_refusal`` the session ends
    instead, once the agent has the error, and ``run`` raises `PermissionError`.
    When HoloTab stops the channel on its own, the waiting command and every later one fail at once with the reason.
    ``upload_roots`` are the only folders HoloTab may upload files from; without them it refuses uploads.
    """

    environment = {"kind": "web", "host": "user_device"}
    startup_hint = "HoloTab must be installed in Chrome with `Connect to desktop apps` turned on"

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
        holotab: HoloTabClient | None = None,
        label: str | Callable[[], str] | None = None,
        client: str = DEFAULT_CLIENT,
        consent: Callable[[], bool] | None = None,
        upload_roots: Sequence[str] | None = None,
        stop_on_refusal: bool = False,
    ) -> None:
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.holotab = holotab
        self.label = label
        self.client = client
        self.consent = consent
        self.upload_roots = None if upload_roots is None else list(upload_roots)
        self.stop_on_refusal = stop_on_refusal
        self._allowed: bool | None = None
        self._refusal: str | None = None
        self._commands: _Commands | None = None
        self._channel = _Channel()
        self._opening: tuple[_Channel, Future[None]] | None = None
        self._opened: _Channel | None = None
        self._opening_lock = threading.Lock()

    @property
    def refusal(self) -> str | None:
        """Why the user refused this session, in HoloTab or through ``consent``; None while not refused."""
        return self._refusal

    def holotab_client(self) -> HoloTabClient:
        if self.holotab is None:
            self.holotab = process_client(self.client, resolve_token(self.api_key))
        return self.holotab

    def preflight(self) -> None:
        """Connect to HoloTab, so its hub is found while the bridge waits for its first command."""
        self.holotab_client().start()

    def create_web_driver(self) -> WebDriverInterface:
        try:
            from hai_drivers.web.holotab.driver import make_holotab_web_driver
        except ImportError as exc:
            raise ImportError(INSTALL_HINT) from exc
        self._commands = _Commands(self)
        return make_holotab_web_driver(self._commands, command_timeout=COMMAND_TIMEOUT_S)

    async def run(self) -> None:
        await super().run()
        if self._refusal is not None and self.stop_on_refusal:
            raise PermissionError(self._refusal)

    async def interrupt_driver(self) -> None:
        """A stop must not wait for Chrome: closing sends `STOP_CHANNEL` and releases the waiting command."""
        await asyncio.to_thread(self.close_channel)

    async def _deliver(
        self, exchange: CommandExchange, command_id: str, command_uid: str, result: Json, error: str | None
    ) -> None:
        await super()._deliver(exchange, command_id, command_uid, result, error)
        if self._refusal is not None and self.stop_on_refusal:
            logger.warning("ending the HoloTab session: %s", self._refusal)
            self.request_stop()

    def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[Json, str | None]:
        if self._commands is not None and self._commands.destroyed and not self._stop_event.is_set():
            self._driver = self.create_driver()
        return super()._dispatch(name, args)

    def close_channel(self) -> None:
        """Stops the channel if it was opened or is opening, and frees the commands waiting on it; never waits for
        Chrome."""
        with self._opening_lock:
            channel, self._channel = self._channel, _Channel()
            opening = None if self._opening is None else self._opening[1]
            failed = opening is not None and opening.done() and opening.exception() is not None
            opened = self._opened is not None or (opening is not None and not failed)
            self._opened = self._opening = None
        channel.end(DESTROYED)
        if opened:
            self.holotab_client().stop(self.session_id)

    def _open(self) -> None:
        """Starts serving this session in Chrome, waiting at most ``OPEN_HOLD_S``. A failure leaves nothing running,
        so the next command retries; a serve still waiting for the user's answer is kept for the next command."""
        channel = self._channel
        if channel.ended.done():
            raise RuntimeError(channel.ended.result())
        if self._opened is channel:
            return
        if self._refusal is not None:
            raise PermissionError(self._refusal)
        if not self._consented():
            self._refusal = "the user did not allow the agent to use their Chrome"
            raise PermissionError(self._refusal)
        if channel.ended.done():
            raise RuntimeError(channel.ended.result())
        with self._opening_lock:
            if self._opening is None or self._opening[0] is not channel:
                future: Future[None] = Future()
                threading.Thread(
                    target=self._serve_in_background, args=(channel, future), name="holotab-open", daemon=True
                ).start()
                self._opening = (channel, future)
            future = self._opening[1]
        wait([future], OPEN_HOLD_S)
        if not future.done():
            if self.holotab_client().consent_pending(self.session_id):
                raise RuntimeError(
                    f"Waiting for the user to allow {self.client} in HoloTab's side panel: "
                    "run the same action again in a moment"
                )
            raise RuntimeError("HoloTab is still opening the Chrome channel: run the same action again in a moment")
        with self._opening_lock:
            if self._opening is not None and self._opening[1] is future:
                self._opening = None
        future.result()
        with self._opening_lock:
            if not channel.ended.done():
                self._opened = channel

    def _serve_in_background(self, channel: _Channel, future: Future[None]) -> None:
        try:
            from hai_drivers.web.holotab.client import HoloTabRefused

            holotab = self.holotab_client()
            holotab.start()
            if not holotab.wait_connected(CONNECT_WAIT_S):
                raise RuntimeError(holotab.incompatible or NOT_CONNECTED)
            label = self.label() if callable(self.label) else self.label or self.client
            try:
                holotab.serve(
                    self.session_id,
                    label=label,
                    upload_roots=self.upload_roots,
                    on_stopped=lambda reason: channel.end(f"HoloTab stopped the channel ({reason})"),
                    timeout_s=SERVE_TIMEOUT_S,
                )
            except HoloTabRefused as exc:
                if exc.code == "DENIED":
                    self._refusal = str(exc)
                    raise PermissionError(self._refusal) from exc
                raise
            if channel.ended.done():
                holotab.stop(self.session_id)
                raise RuntimeError(channel.ended.result())
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(None)

    def _consented(self) -> bool:
        if self.consent is None:
            return True
        if self._allowed is None:
            self._allowed = bool(self.consent())
        return self._allowed


class _Channel:
    """One opening of the session in Chrome; ``ended`` holds why its commands fail from then on."""

    def __init__(self) -> None:
        self.ended: Future[str] = Future()

    def end(self, reason: str) -> None:
        with contextlib.suppress(InvalidStateError):
            self.ended.set_result(reason)


class _Commands:
    """The driver's command service: JavaScript, cookies and storage never reach Chrome, ``destroy`` closes the channel
    without asking it, and every other command opens the channel first."""

    def __init__(self, bridge: HoloTabBrowserBridge) -> None:
        self.bridge = bridge
        self.destroyed = False

    def execute_command(self, name: str, args: dict[str, Any], timeout: float = COMMAND_TIMEOUT_S) -> Any:
        if name in NOT_SUPPORTED:
            raise RuntimeError(
                f"{name} is not supported by HoloTab: it does not run JavaScript, or read or change "
                "cookies or local storage"
            )
        if name == "destroy":
            if not self.destroyed:
                self.destroyed = True
                self.bridge.close_channel()
            return None
        if self.destroyed:
            raise RuntimeError(DESTROYED)
        started = time.monotonic()
        self.bridge._open()
        left = max(timeout - (time.monotonic() - started), MIN_COMMAND_WAIT_S)
        return self.bridge.holotab_client().execute(self.bridge.session_id, name, args, left)

    def __enter__(self) -> _Commands:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def install_host() -> None:
    """Registers HoloTab's hub with Chrome, so HoloTab can start it and reach this process."""
    try:
        from hai_drivers.web.holotab.install import install_host as install
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    install()


_process_clients: dict[tuple[str, str], HoloTabClient] = {}
_process_lock = threading.Lock()


def process_client(name: str, key: str) -> HoloTabClient:
    """The one HoloTab client this process shares between its bridges for the app ``name`` and the H API ``key``."""
    try:
        from hai_drivers.web.holotab.client import HoloTabClient
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    with _process_lock:
        holotab = _process_clients.get((name, key))
        if holotab is None:
            holotab = _process_clients[(name, key)] = HoloTabClient(name, key)
            atexit.register(_close_at_exit, holotab)
        return holotab


def _close_at_exit(holotab: HoloTabClient) -> None:
    """The bridges stop first, so the `STOP_CHANNEL` each one sends still reaches HoloTab."""
    try:
        stop_bridges()
    except TimeoutError as exc:
        logger.warning("closing the HoloTab client before every bridge stopped: %s", exc)
    finally:
        holotab.close()

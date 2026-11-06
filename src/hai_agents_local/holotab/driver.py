"""A `WebDriverInterface` whose every call is a command the HoloTab extension runs in the user's own Chrome."""

from __future__ import annotations

import base64
import functools
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

from hai_drivers.web.interface import WebDriverInterface
from pydantic import BaseModel, ValidationError

from .commands import DEFAULT_COMMAND_TIMEOUT_S, LocalCommandServer

logger = logging.getLogger(__name__)

EXTENSION_NATIVE = frozenset({"observation_bundle", "screenshot_and_metadata", "webpage_metadata"})
EXECUTOR_RUNS = frozenset(
    {
        "click_at",
        "close_tab",
        "drag_and_drop",
        "find_in_page",
        "get_select_at",
        "get_viewport_html",
        "open_new_tab",
        "press_and_release_keys",
        "scroll_at",
        "scroll_page",
        "set_select_option_idx",
        "write_at",
    }
)


class LocalChromeDriver(WebDriverInterface):
    """The methods are generated from the interface, so one added upstream arrives wired, with the parameter names the
    model is shown. The extension eases the pointer to each point it is sent, like a hand (`glides`).

    ``opener`` runs before the first command and ``closer`` once on ``destroy`` if the opener succeeded: nothing opens
    in the user's Chrome until the agent first uses it. An opener that raises fails that command only; the next
    command runs it again. Only ``destroy`` is final.
    """

    glides = True

    def __init__(
        self,
        server: LocalCommandServer,
        timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
        *,
        opener: Callable[[], None] | None = None,
        closer: Callable[[], None] | None = None,
    ) -> None:
        self._server = server
        self._timeout_s = timeout_s
        self._opener = opener
        self._closer = closer
        self._opened = opener is None
        self._destroyed = False
        self._open_lock = threading.Lock()

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    def _call(self, name: str, payload: dict[str, Any]) -> Any:
        self._ensure_open()
        return _revive(name, self._server.submit(name, payload, self._timeout_s))

    def _ensure_open(self) -> None:
        with self._open_lock:
            if self._destroyed:
                raise RuntimeError("the Chrome driver was destroyed")
            if not self._opened:
                assert self._opener is not None
                self._opener()
                self._opened = True

    def destroy(self) -> None:
        with self._open_lock:
            if self._destroyed:
                return
            opened, self._destroyed = self._opened, True
        try:
            if opened and self._closer is not None:
                self._closer()
        finally:
            self._server.stop()


def _command(name: str) -> Any:
    signature = inspect.signature(getattr(WebDriverInterface, name))

    def call(self: LocalChromeDriver, *args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        return self._call(name, {key: value for key, value in bound.arguments.items() if key != "self"})

    call.__name__ = name
    call.__dict__["__signature__"] = signature
    call.__doc__ = getattr(WebDriverInterface, name).__doc__
    return call


@functools.cache
def _returns(name: str) -> Any:
    """What the interface says a command gives back; `eval_str`, since its module postpones annotations."""
    try:
        return inspect.signature(getattr(WebDriverInterface, name), eval_str=True).return_annotation
    except (NameError, TypeError, ValueError):
        return inspect.Parameter.empty


def _revive(name: str, value: Any) -> Any:
    """Undoes the wire encoding: base64 text back to bytes, a dict back to the model the interface names."""
    wanted = _returns(name)
    if wanted is bytes and isinstance(value, str):
        return base64.b64decode(value.split(",", 1)[1] if value.startswith("data:") else value)
    if not isinstance(value, dict) or not isinstance(wanted, type) or not issubclass(wanted, BaseModel):
        return value
    try:
        return wanted.model_validate(value)
    except ValidationError:
        logger.debug("%s returned something %s does not accept", name, wanted.__name__)
        return value


for _name in sorted(WebDriverInterface.__abstractmethods__ | EXTENSION_NATIVE | EXECUTOR_RUNS):
    if getattr(LocalChromeDriver, _name, None) is None or getattr(LocalChromeDriver, _name) is getattr(
        WebDriverInterface, _name, None
    ):
        setattr(LocalChromeDriver, _name, _command(_name))
LocalChromeDriver.__abstractmethods__ = frozenset()

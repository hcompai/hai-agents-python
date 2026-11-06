"""A `WebDriverInterface` whose every call is a command the HoloTab extension runs in the user's own Chrome."""

from __future__ import annotations

import base64
import functools
import inspect
import time
import typing
from collections.abc import Callable
from typing import Any

from hai_drivers.web.interface import WebDriverInterface
from pydantic import BaseModel, ValidationError

from .commands import DEFAULT_COMMAND_TIMEOUT_S, LocalCommandServer

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
MIN_COMMAND_WAIT_S = 1.0
NOT_SUPPORTED = frozenset({"add_cookies", "delete_cookies", "get_cookies", "get_local_storage", "set_local_storage"})


class LocalChromeDriver(WebDriverInterface):
    """The methods are generated from the interface, so one added upstream arrives wired, with the parameter names the
    model is shown. The extension eases the pointer to each point it is sent, like a hand (`glides`). Opening and
    closing the channel in Chrome is the bridge's: the driver calls ``opener`` before each command it forwards to
    ``server``, and the time spent there counts against the command's wait."""

    glides = True

    def __init__(
        self,
        server: LocalCommandServer,
        timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
        opener: Callable[[], None] = lambda: None,
    ) -> None:
        self.server = server
        self.timeout_s = timeout_s
        self.opener = opener

    def _call(self, name: str, payload: dict[str, Any]) -> Any:
        started = time.monotonic()
        self.opener()
        left = max(self.timeout_s - (time.monotonic() - started), MIN_COMMAND_WAIT_S)
        return _revive(name, self.server.submit(name, payload, left))

    def destroy(self) -> None:
        self.server.stop()


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


def _not_supported(name: str) -> Any:
    def call(self: LocalChromeDriver, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"{name} is not supported by HoloTab: it does not read or change cookies or local storage")

    call.__name__ = name
    call.__dict__["__signature__"] = inspect.signature(getattr(WebDriverInterface, name))
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
    """Undoes the wire encoding: base64 text back to bytes, a JSON array back to the tuple, a dict back to the model
    the interface names. A dict the model refuses raises here, not at the caller's first attribute."""
    wanted = _returns(name)
    if wanted is bytes and isinstance(value, str):
        return base64.b64decode(value.split(",", 1)[1] if value.startswith("data:") else value)
    if typing.get_origin(wanted) is tuple and isinstance(value, list):
        return tuple(value)
    if not isinstance(value, dict) or not isinstance(wanted, type) or not issubclass(wanted, BaseModel):
        return value
    try:
        return wanted.model_validate(value)
    except ValidationError as exc:
        raise RuntimeError(f"Chrome answered {name} with something {wanted.__name__} does not accept: {exc}") from exc


for _name in sorted(NOT_SUPPORTED):
    setattr(LocalChromeDriver, _name, _not_supported(_name))
for _name in sorted((WebDriverInterface.__abstractmethods__ | EXTENSION_NATIVE | EXECUTOR_RUNS) - NOT_SUPPORTED):
    if getattr(LocalChromeDriver, _name, None) is None or getattr(LocalChromeDriver, _name) is getattr(
        WebDriverInterface, _name, None
    ):
        setattr(LocalChromeDriver, _name, _command(_name))
LocalChromeDriver.__abstractmethods__ = frozenset()

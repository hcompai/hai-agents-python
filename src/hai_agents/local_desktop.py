"""Local desktop sidecar — runs on the user's machine, polls AgP for commands, executes them locally.

Typical usage::

    import asyncio
    from hai_agents import LocalDesktopClient, LocalDesktopClientConfig

    async def main():
        config = LocalDesktopClientConfig(environment_id="my-mac", api_key="...")
        async with LocalDesktopClient(config) as client:
            await client.run()

    asyncio.run(main())

Install the optional desktop extra first::

    pip install "hai-agents[desktop]"
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import subprocess
import sys
import time
import uuid as _uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

try:
    import pyautogui  # pyright: ignore[reportMissingModuleSource]
except ImportError:
    pyautogui = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_AGP_BASE_URL = "https://agp.eu.hcompany.ai"
_TRANSIENT_STATUS_CODES = frozenset({502, 503, 504})
_WINDOWS_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_WINDOWS_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def session_id_from_environment_id(environment_id: str, api_key: str) -> str:
    """Deterministic UUID5 from (environment_id, api_key) — same formula as the sagent proxy."""
    return str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{api_key}.{environment_id}"))


class LocalDesktopClientConfig(BaseModel):
    """Configuration for :class:`LocalDesktopClient`."""

    environment_id: str
    """Human-readable name of the machine (e.g. ``"my-mac"``).
    Used to derive ``session_id`` via UUID5 so both the sidecar and the caller
    agree on the routing UUID without explicit coordination."""

    api_key: str = ""
    """Bearer token. Defaults to the ``AGP_SERVICE_KEY`` or ``AGP_API_KEY`` env var."""

    session_id: str = ""
    """Derived from ``environment_id`` + ``api_key`` via UUID5 if not set explicitly."""

    base_url: str = _AGP_BASE_URL
    """AgP base URL."""

    long_poll_seconds: int = Field(default=20, ge=1)
    """How many seconds to ask the server to hold each long-poll request."""

    long_poll_timeout_buffer_s: float = Field(default=1.0, gt=0)
    """Extra seconds added to ``long_poll_seconds`` for the HTTP read timeout."""

    post_result_timeout_s: float = Field(default=10.0, gt=0)
    """Per-request timeout when posting a command result."""

    post_result_retries: int = Field(default=2, ge=0)
    fivexx_max_retries: int = Field(default=2, ge=0)
    fivexx_backoff_s: float = Field(default=1.5, gt=0)
    rate_limit_backoff_s: float = Field(default=2.0, gt=0)
    max_reconnect_delay_s: float = Field(default=60.0, gt=0)

    @model_validator(mode="after")
    def _resolve_defaults(self) -> Self:
        if not self.api_key:
            self.api_key = os.getenv("AGP_SERVICE_KEY") or os.getenv("AGP_API_KEY") or ""
        if not self.api_key:
            raise ValueError("api_key is required (or set AGP_SERVICE_KEY / AGP_API_KEY)")
        if not self.session_id:
            self.session_id = session_id_from_environment_id(self.environment_id, self.api_key)
        return self


class _AuthError(Exception):
    pass


class _SessionNotFoundError(Exception):
    pass


def _serialize_result(value: Any) -> Any:
    """Make a driver return value JSON-serializable for the result POST."""
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_serialize_result(v) for v in value]
    return value


def _deserialize_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Undo command_proxy serialization for args that need special handling."""
    if name == "write_file" and "content" in args and isinstance(args["content"], str):
        args = dict(args)
        args["content"] = base64.b64decode(args["content"])
    if name == "run_command" and args.get("cwd") is not None:
        args = dict(args)
        args["cwd"] = Path(args["cwd"])
    return args


class _RunCommandResponse(BaseModel):
    returncode: int
    stdout: str
    stderr: str
    exception: str | None = None


def _detached_popen_kwargs() -> dict[str, Any]:
    """Return platform-specific Popen kwargs for long-running detached commands."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _WINDOWS_DETACHED_PROCESS | _WINDOWS_CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return kwargs


class _LocalDesktopDriver:
    """Local desktop driver using pyautogui + pynput (requires ``hai-agents[desktop]``)."""

    def __init__(self) -> None:
        if pyautogui is None:
            raise ImportError(
                "Local desktop control requires pyautogui and pynput. Install with: pip install 'hai-agents[desktop]'"
            )

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0

    # -- Screenshots & observation --

    def screenshot_png_bytes(self) -> bytes:
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def get_screen_size(self) -> tuple[int, int]:
        s = pyautogui.size()
        return (s.width, s.height)

    def get_mouse_position(self) -> tuple[int, int]:
        p = pyautogui.position()
        return (p.x, p.y)

    def get_number_of_pixels_scrolled_per_click(self) -> int:
        return {"darwin": 20, "win32": 120}.get(sys.platform, 53)

    def get_accessibility_tree(self) -> str:
        raise NotImplementedError("Accessibility tree is not supported on this driver")

    # -- Mouse --

    def mouse_move_to(self, x: int, y: int) -> None:
        pyautogui.moveTo(x, y)

    def mouse_press(self, button: str = "left") -> None:
        pyautogui.mouseDown(button=button)

    def mouse_release(self, button: str = "left") -> None:
        pyautogui.mouseUp(button=button)

    def click(self, x: int, y: int, button: str = "left") -> None:
        pyautogui.click(x, y, button=button)

    def double_click(self, x: int, y: int, button: str = "left", delay_between_clicks: float = 0.05) -> None:
        pyautogui.doubleClick(x, y, button=button, interval=delay_between_clicks)

    def scroll_by_n_clicks(self, direction: str, clicks: int) -> None:
        if direction in ("up", "down"):
            amount = clicks if direction == "up" else -clicks
            pyautogui.scroll(amount)
        else:
            amount = clicks if direction == "right" else -clicks
            pyautogui.hscroll(amount)

    # -- Keyboard --

    def write(self, text: str, delay_between_keys: float = 0.05) -> None:
        pyautogui.write(text, interval=delay_between_keys)

    def hotkey(self, keys: list[str]) -> None:
        pyautogui.hotkey(*keys)

    def tap_key(self, key: str) -> None:
        pyautogui.press(key)

    def press_key(self, key: str) -> None:
        pyautogui.keyDown(key)

    def release_key(self, key: str) -> None:
        pyautogui.keyUp(key)

    # -- Filesystem & commands --

    def read_file(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def write_file(self, path: str, content: bytes) -> None:
        Path(path).write_bytes(content)

    def run_command(
        self,
        command: list[str],
        timeout: int | None = 60,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        detach: bool = False,
        ignore_errors: bool = False,
    ) -> _RunCommandResponse:
        if detach:
            subprocess.Popen(command, env=env, cwd=cwd, **_detached_popen_kwargs())
            return _RunCommandResponse(returncode=0, stdout="", stderr="")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=cwd,
            )
            return _RunCommandResponse(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except Exception as exc:
            if ignore_errors:
                return _RunCommandResponse(returncode=-1, stdout="", stderr="", exception=str(exc))
            raise


class LocalDesktopClient:
    """Async long-polling sidecar that executes desktop commands on the local machine.

    Polls ``GET /api/v1/commands/{session_id}/commands`` for pending commands,
    dispatches them through the local desktop driver, and posts results back via
    ``POST /api/v1/commands/{command_id}/result``.

    Args:
        config: Connection and retry parameters.
        driver: Optional custom driver. Defaults to :class:`_LocalDesktopDriver`.
    """

    def __init__(
        self,
        config: LocalDesktopClientConfig,
        driver: Any | None = None,
    ) -> None:
        self._config = config
        self._driver = driver or _LocalDesktopDriver()
        self._stop_event = asyncio.Event()
        self._running = False

    async def __aenter__(self) -> "LocalDesktopClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    async def run(self) -> None:
        """Start the polling loop. Returns when :meth:`stop` is called or auth fails."""
        if self._running:
            raise RuntimeError("LocalDesktopClient.run() is already active.")
        self._running = True
        try:
            await self._run()
        finally:
            self._running = False

    async def stop(self) -> None:
        """Signal the polling loop to stop gracefully."""
        self._stop_event.set()

    async def _run(self) -> None:
        self._stop_event.clear()
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            try:
                await self._ensure_session(client)
            except _AuthError as exc:
                logger.error("Auth error during session setup, stopping: %s", exc)
                return
            await self._poll_loop(client)

    async def _ensure_session(self, client: httpx.AsyncClient) -> None:
        base = self._config.base_url
        session_id = self._config.session_id
        check = await client.get(f"{base}/api/v1/trajectories/{session_id}/")
        if check.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise _AuthError(f"Auth error checking session ({check.status_code})")
        if check.status_code == HTTPStatus.OK:
            return
        resp = await client.post(
            f"{base}/api/v1/trajectories/",
            json={"id": session_id, "task": {"type": "interactive"}, "launch": False},
        )
        if resp.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise _AuthError(f"Auth error creating session ({resp.status_code})")
        resp.raise_for_status()

    async def _poll_loop(self, client: httpx.AsyncClient) -> None:
        retry_delay = 1.0
        while not self._stop_event.is_set():
            try:
                commands = await self._fetch_commands(client)
                retry_delay = 1.0
                if commands:
                    await self._process_commands(client, commands)
            except _AuthError as exc:
                logger.error("Auth error, stopping: %s", exc)
                break
            except _SessionNotFoundError as exc:
                raise RuntimeError(str(exc)) from exc
            except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("Connection error: %s. Retrying in %.0fs...", exc, retry_delay)
                if await self._interruptible_sleep(retry_delay):
                    break
                retry_delay = min(retry_delay * 2, self._config.max_reconnect_delay_s)

    async def _fetch_commands(self, client: httpx.AsyncClient) -> list[dict[str, Any]] | None:
        cfg = self._config
        url = f"{cfg.base_url}/api/v1/commands/{cfg.session_id}/commands"
        timeout = cfg.long_poll_seconds + cfg.long_poll_timeout_buffer_s

        for attempt in range(cfg.fivexx_max_retries + 1):
            resp = await client.get(
                url,
                params={"wait_for_seconds": cfg.long_poll_seconds},
                timeout=timeout,
            )
            if resp.status_code == HTTPStatus.NO_CONTENT:
                return None
            if resp.status_code == HTTPStatus.NOT_FOUND:
                raise _SessionNotFoundError(
                    f"Session {cfg.session_id!r} not found. Check the environment_id/api_key pair."
                )
            if resp.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
                raise _AuthError(f"Auth error ({resp.status_code})")
            if resp.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                await self._interruptible_sleep(cfg.rate_limit_backoff_s)
                return None
            if resp.status_code in _TRANSIENT_STATUS_CODES and attempt < cfg.fivexx_max_retries:
                await self._interruptible_sleep((attempt + 1) * cfg.fivexx_backoff_s)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else None
        return None

    async def _post_result(
        self,
        client: httpx.AsyncClient,
        command_id: str,
        command_uid: str,
        result: Any,
        error: str | None,
    ) -> None:
        cfg = self._config
        url = f"{cfg.base_url}/api/v1/commands/{command_id}/result"
        body = {"result": result, "error": error, "command_uid": command_uid}
        for attempt in range(cfg.post_result_retries + 1):
            try:
                resp = await client.post(url, json=body, timeout=cfg.post_result_timeout_s)
                if resp.is_success:
                    return
                logger.warning("POST result for %s returned %s", command_id, resp.status_code)
            except httpx.HTTPError as exc:
                logger.warning("POST result for %s failed (attempt %s): %s", command_id, attempt + 1, exc)
            if attempt < cfg.post_result_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
        logger.error(
            "Failed to deliver result for command %s after %s attempts", command_id, cfg.post_result_retries + 1
        )

    def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[Any, str | None]:
        method: Callable[..., Any] | None = getattr(self._driver, name, None)
        if method is None:
            return None, f"Unknown command: {name!r}"
        tic = time.monotonic()
        try:
            raw_args = _deserialize_args(name, args)
            result = method(**raw_args)
            logger.info("Command %s dispatched in %.2fs", name, time.monotonic() - tic)
            return _serialize_result(result), None
        except NotImplementedError:
            return None, f"Command {name!r} is not supported on this driver"
        except Exception as exc:
            logger.warning("Command %s raised: %s", name, exc)
            return None, str(exc)

    async def _process_commands(self, client: httpx.AsyncClient, commands: list[dict[str, Any]]) -> None:
        for cmd in commands:
            if self._stop_event.is_set():
                break
            cmd_id = cmd.get("id")
            cmd_uid = cmd.get("command_uid")
            if cmd_id is None or cmd_uid is None:
                logger.warning("Skipping command with missing id or command_uid: %s", cmd)
                continue
            name: str = cmd.get("name", "")
            args: dict[str, Any] = cmd.get("args") or {}
            logger.info("Processing command %s (%s)", cmd_id, name)
            result, error = await asyncio.to_thread(self._dispatch, name, args)
            await self._post_result(client, cmd_id, cmd_uid, result, error)

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep up to ``seconds``. Returns ``True`` if stop was requested."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

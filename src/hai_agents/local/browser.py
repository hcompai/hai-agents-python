from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .bridge import LocalBridge

logger = logging.getLogger(__name__)

DEFAULT_DEBUG_PORT = 9222
CHROME_STARTUP_TIMEOUT_S = 20.0
CHROME_PROFILE_DIR = Path.home() / ".hai" / "chrome-profile"

_launch_lock = threading.Lock()

_CHROME_CANDIDATES = {
    "Darwin": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ),
    "Windows": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ),
}
_CHROME_COMMANDS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")


class BrowserBridge(LocalBridge):
    """Serves browser commands by attaching Selenium to a Chrome debugging port on this machine."""

    capability = "browser"

    def __init__(
        self,
        environment_id: str,
        *,
        debugging_port: int = DEFAULT_DEBUG_PORT,
        api_key: str | None = None,
        base_url: str | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.debugging_port = debugging_port

    def create_driver(self) -> Any:
        try:
            from hai_drivers.web.selenium import SeleniumWebDriver
        except ImportError as exc:
            raise ImportError(
                "Local browser control requires extra deps. Install with: pip install 'hai-agents[browser]'"
            ) from exc
        ensure_local_chrome(self.debugging_port)
        return SeleniumWebDriver(debugging_port=self.debugging_port)

    def driver_interface(self) -> type:
        from hai_drivers.web.interface import WebDriverInterface

        return WebDriverInterface


def ensure_local_chrome(port: int = DEFAULT_DEBUG_PORT) -> None:
    """Reuse a Chrome already listening on ``port``, or launch one with a dedicated profile."""
    with _launch_lock:
        if _debugger_listening(port):
            return
        binary = next((p for p in _CHROME_CANDIDATES.get(platform.system(), ()) if Path(p).exists()), None) or next(
            (found for command in _CHROME_COMMANDS if (found := shutil.which(command))), None
        )
        if binary is None:
            raise RuntimeError(
                "Google Chrome was not found. Install Chrome, or start a browser yourself with "
                f"--remote-debugging-port={port}."
            )
        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("launching Chrome with remote debugging on port %d (profile: %s)", port, CHROME_PROFILE_DIR)
        process = subprocess.Popen(
            [
                binary,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={CHROME_PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + CHROME_STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if _debugger_listening(port):
                return
            if process.poll() is not None:
                raise RuntimeError(f"Chrome exited with code {process.returncode} before opening debugging port {port}")
            time.sleep(0.25)
        process.kill()
        raise RuntimeError(f"Chrome did not open debugging port {port} within {CHROME_STARTUP_TIMEOUT_S:.0f}s")


def _debugger_listening(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False

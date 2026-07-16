"""`hai doctor`: read-only diagnostics for login, platform access, and local control, with fix-its."""

from __future__ import annotations

import importlib.util
import socket
import sys
from dataclasses import dataclass

from hai_agents_common import credentials

DEFAULT_CHROME_DEBUG_PORT = 9222


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


def check_login(api_key: str | None) -> CheckResult:
    if credentials.current_api_key(api_key):
        return CheckResult("login", True, f"API key found ({credentials.source(api_key)})")
    return CheckResult(
        "login",
        False,
        "no API key configured",
        fix=f"run `hai login`, set {credentials.API_KEY_VAR}, or pass --api-key",
    )


def check_platform(api_key: str | None, base_url: str | None) -> CheckResult:
    endpoint = credentials.resolve_base_url(base_url) or "(SDK default)"
    try:
        client = credentials.make_client(api_key=api_key, base_url=base_url)
        client.agents.list_agents(page=1, size=1)
    except Exception as exc:
        return CheckResult(
            "platform",
            False,
            f"cannot query {endpoint}: {exc}",
            fix="check the key and network; `hai whoami` shows the resolved endpoint",
        )
    return CheckResult("platform", True, f"authenticated against {endpoint}")


def check_browser() -> CheckResult:
    if importlib.util.find_spec("hai_drivers") is None or importlib.util.find_spec("hai_drivers.web") is None:
        return CheckResult(
            "browser", True, "local browser control not installed; add it with: pip install 'hai-agents[browser]'"
        )
    if _port_in_use(DEFAULT_CHROME_DEBUG_PORT):
        detail = f"deps installed; a debuggable Chrome is listening on port {DEFAULT_CHROME_DEBUG_PORT} (will attach)"
    else:
        detail = f"deps installed; port {DEFAULT_CHROME_DEBUG_PORT} is free (a Chrome will be launched on demand)"
    return CheckResult("browser", True, detail)


def check_desktop() -> CheckResult:
    if importlib.util.find_spec("hai_drivers") is None or importlib.util.find_spec("hai_drivers.desktop") is None:
        return CheckResult(
            "desktop", True, "local desktop control not installed; add it with: pip install 'hai-agents[desktop]'"
        )
    if sys.platform != "darwin":
        return CheckResult("desktop", True, "deps installed")
    missing = _missing_macos_grants()
    if missing:
        from hai_agents_local.desktop import ACCESSIBILITY_SETTINGS_URL, SCREEN_RECORDING_SETTINGS_URL

        return CheckResult(
            "desktop",
            False,
            f"deps installed, but this terminal is missing macOS grants: {', '.join(missing)}",
            fix="grant them in System Settings -> Privacy & Security, then restart this terminal: "
            f"{ACCESSIBILITY_SETTINGS_URL} and {SCREEN_RECORDING_SETTINGS_URL}",
        )
    return CheckResult("desktop", True, "deps installed; Accessibility and Screen Recording granted")


def _missing_macos_grants() -> list[str]:
    # Non-prompting variants keep the doctor read-only; the bridge preflight does the prompting.
    from ApplicationServices import AXIsProcessTrusted
    from Quartz import CGPreflightScreenCaptureAccess

    missing = []
    if not AXIsProcessTrusted():
        missing.append("Accessibility")
    if not CGPreflightScreenCaptureAccess():
        missing.append("Screen Recording")
    return missing


def _port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def run_checks(api_key: str | None, base_url: str | None) -> list[CheckResult]:
    login = check_login(api_key)
    checks = [login]
    if login.ok:
        checks.append(check_platform(api_key, base_url))
    checks.extend([check_browser(), check_desktop()])
    return checks

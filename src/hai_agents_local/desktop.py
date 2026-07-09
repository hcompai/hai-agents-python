from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .bridge import LocalBridge

if TYPE_CHECKING:
    from hai_drivers.desktop.local import LocalDesktopDriver


def ensure_macos_input_permissions() -> None:
    """Fail fast when macOS would silently drop synthesized input, triggering the native grant prompts.

    Accessibility and Screen Recording are independent TCC grants; without the former, pyautogui
    events are dropped with no error and an agent burns steps on screenshots that never change.
    """
    if sys.platform != "darwin":
        return
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

    missing = []
    if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
        missing.append("Accessibility (moves the mouse and types)")
    if not (CGPreflightScreenCaptureAccess() or CGRequestScreenCaptureAccess()):
        missing.append("Screen Recording (reads the screen)")
    if missing:
        raise PermissionError(
            "macOS blocks this Python process from controlling the desktop. Missing permissions: "
            + "; ".join(missing)
            + ". Grant them to the app that runs Python (your terminal) in System Settings -> "
            "Privacy & Security, then restart that app and run again; grants only apply to a fresh process."
        )


class PyautoguiDesktopBridge(LocalBridge["LocalDesktopDriver"]):
    """Serves desktop environments (mouse, keyboard, screen, files, shell) on this machine via pyautogui."""

    environment_kind = "desktop"

    def create_driver(self) -> LocalDesktopDriver:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        try:
            from hai_drivers.desktop.local import LocalDesktopDriver
        except ImportError as exc:
            raise ImportError(
                "Local desktop control requires extra deps. Install with: pip install 'hai-agents[desktop]'"
            ) from exc
        ensure_macos_input_permissions()
        return LocalDesktopDriver()

    def driver_interface(self) -> type:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        from hai_drivers.desktop.interface import DesktopDriverInterface

        return DesktopDriverInterface

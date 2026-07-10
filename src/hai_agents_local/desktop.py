from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .bridge import LocalBridge

if TYPE_CHECKING:
    from hai_drivers.desktop.local import LocalDesktopDriver

ACCESSIBILITY_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
SCREEN_RECORDING_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"

# HiDPI displays capture at backing resolution (a 5K display yields ~14 MP PNGs), which blows past
# the platform's request body limit when posted; 1920 matches the width production desktop agents use.
DEFAULT_SCREENSHOT_MAX_WIDTH = 1920


def ensure_macos_input_permissions() -> None:
    """Fail fast when macOS would silently drop synthesized input, triggering the native grant prompts.

    Accessibility and Screen Recording are independent TCC grants; without the former, pyautogui
    events are dropped with no error and an agent burns steps on screenshots that never change.
    """
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
            "Privacy & Security, then restart that app and run again; grants only apply to a fresh process. "
            f"Open the panes directly: {ACCESSIBILITY_SETTINGS_URL} and {SCREEN_RECORDING_SETTINGS_URL}"
        )


class PyautoguiDesktopBridge(LocalBridge["LocalDesktopDriver"]):
    """Serves desktop environments (mouse, keyboard, screen, files, shell) on this machine via pyautogui."""

    environment_kind = "desktop"

    def __init__(
        self, *args: object, screenshot_max_width: int | None = DEFAULT_SCREENSHOT_MAX_WIDTH, **kwargs: object
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.screenshot_max_width = screenshot_max_width

    def create_driver(self) -> LocalDesktopDriver:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        try:
            from hai_drivers.desktop.local import LocalDesktopDriver
        except ImportError as exc:
            raise ImportError(
                "Local desktop control requires extra deps. Install with: pip install 'hai-agents[desktop]'"
            ) from exc
        if sys.platform == "darwin":
            ensure_macos_input_permissions()
        return LocalDesktopDriver(screenshot_max_width=self.screenshot_max_width)

    def driver_interface(self) -> type:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        from hai_drivers.desktop.interface import DesktopDriverInterface

        return DesktopDriverInterface

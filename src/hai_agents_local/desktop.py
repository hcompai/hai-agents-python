from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Literal

from .bridge import LocalBridge, TokenSource

if TYPE_CHECKING:
    from hai_drivers.desktop.interface import DesktopDriverInterface

ACCESSIBILITY_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
SCREEN_RECORDING_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"

ImageFormat = Literal["png", "jpeg", "webp"]

DEFAULT_MAX_WIDTH = 1920
DEFAULT_IMAGE_FORMAT: ImageFormat = "jpeg"
DEFAULT_QUALITY = 85


def ensure_macos_input_permissions(prompt: bool = True) -> None:
    """Fail fast when macOS would silently drop synthesized input, triggering the native grant prompts.

    Accessibility and Screen Recording are independent TCC grants; without the former, pyautogui
    events are dropped with no error and an agent burns steps on screenshots that never change.
    Prompting must happen on the main thread; pass prompt=False when checking from a worker.
    """
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

    missing = []
    if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}):
        missing.append("Accessibility (moves the mouse and types)")
    if not (CGPreflightScreenCaptureAccess() or (prompt and CGRequestScreenCaptureAccess())):
        missing.append("Screen Recording (reads the screen)")
    if missing:
        raise PermissionError(
            "macOS blocks this Python process from controlling the desktop. Missing permissions: "
            + "; ".join(missing)
            + ". Grant them to the app that runs Python (your terminal) in System Settings -> "
            "Privacy & Security, then restart that app and run again; grants only apply to a fresh process. "
            f"Open the panes directly: {ACCESSIBILITY_SETTINGS_URL} and {SCREEN_RECORDING_SETTINGS_URL}"
        )


class PyautoguiDesktopBridge(LocalBridge["DesktopDriverInterface"]):
    """Serves desktop environments (mouse, keyboard, screen, files, shell) on this machine via pyautogui.

    Screenshots are downscaled and encoded here, before they cross the network; set every
    knob to None to serve raw native-resolution captures.
    """

    environment_kind = "desktop"

    def __init__(
        self,
        environment_id: str | None = None,
        *,
        api_key: TokenSource,
        base_url: str | None = None,
        session_id: str | None = None,
        max_width: int | None = DEFAULT_MAX_WIDTH,
        max_height: int | None = None,
        image_format: ImageFormat | None = DEFAULT_IMAGE_FORMAT,
        quality: int = DEFAULT_QUALITY,
    ) -> None:
        super().__init__(environment_id, api_key=api_key, base_url=base_url, session_id=session_id)
        self.max_width = max_width
        self.max_height = max_height
        self.image_format = image_format
        self.quality = quality

    def preflight(self) -> None:
        if sys.platform == "darwin":
            ensure_macos_input_permissions(prompt=True)

    def create_driver(self) -> DesktopDriverInterface:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        try:
            from hai_drivers.desktop.local import LocalDesktopDriver
            from hai_drivers.desktop.scaled import ScaledDesktopDriver
        except ImportError as exc:
            raise ImportError(
                "Local desktop control requires hai-drivers>=0.1.2. Install with: pip install 'hai-agents[desktop]'"
            ) from exc
        if sys.platform == "darwin":
            # create_driver runs on a bridge worker thread, where TCC prompts cannot appear;
            # preflight() prompted earlier on the caller's thread, so only re-check here.
            ensure_macos_input_permissions(prompt=False)
        driver = LocalDesktopDriver()
        if self.max_width is None and self.max_height is None and self.image_format is None:
            return driver
        return ScaledDesktopDriver(
            driver,
            max_width=self.max_width,
            max_height=self.max_height,
            image_format=self.image_format,
            quality=self.quality,
        )

    def driver_interface(self) -> type:
        # Runtime import: hai-drivers is absent unless installed with hai-agents[desktop].
        from hai_drivers.desktop.interface import DesktopDriverInterface

        return DesktopDriverInterface

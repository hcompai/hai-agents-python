from __future__ import annotations

from typing import TYPE_CHECKING

from .bridge import LocalBridge

if TYPE_CHECKING:
    from hai_drivers.desktop.local import LocalDesktopDriver


class PyautoguiDesktopBridge(LocalBridge["LocalDesktopDriver"]):
    """Serves desktop environments (mouse, keyboard, screen, files, shell) on this machine via pyautogui."""

    environment_kind = "desktop"

    def create_driver(self) -> LocalDesktopDriver:
        # Runtime import: hai-drivers is an optional extra, absent unless
        # installed with hai-agents[desktop].
        try:
            from hai_drivers.desktop.local import LocalDesktopDriver
        except ImportError as exc:
            raise ImportError(
                "Local desktop control requires extra deps. Install with: pip install 'hai-agents[desktop]'"
            ) from exc
        return LocalDesktopDriver()

    def driver_interface(self) -> type:
        from hai_drivers.desktop.interface import DesktopDriverInterface

        return DesktopDriverInterface

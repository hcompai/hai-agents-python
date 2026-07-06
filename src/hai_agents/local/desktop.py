from __future__ import annotations

from typing import Any

from .bridge import LocalBridge


class DesktopBridge(LocalBridge):
    """Serves desktop commands (mouse, keyboard, screen, files, shell) on this machine."""

    capability = "desktop"

    def create_driver(self) -> Any:
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

"""Local control: serve agent commands on this machine's browser or desktop via hai-drivers."""

from .bridge import LocalBridge
from .browser import SeleniumBrowserBridge
from .desktop import PyautoguiDesktopBridge
from .manager import BridgeManager, ensure_bridges, stop_bridges

__all__ = [
    "BridgeManager",
    "LocalBridge",
    "PyautoguiDesktopBridge",
    "SeleniumBrowserBridge",
    "ensure_bridges",
    "stop_bridges",
]

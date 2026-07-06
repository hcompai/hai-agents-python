"""Local control: serve agent commands on this machine's browser or desktop via hai-drivers."""

from .bridge import BridgeBusyError, LocalBridge, session_id_from_environment_id
from .browser import SeleniumBrowserBridge
from .desktop import PyautoguiDesktopBridge
from .manager import BridgeManager, ensure_bridges, stop_bridges

__all__ = [
    "BridgeBusyError",
    "BridgeManager",
    "LocalBridge",
    "PyautoguiDesktopBridge",
    "SeleniumBrowserBridge",
    "ensure_bridges",
    "session_id_from_environment_id",
    "stop_bridges",
]

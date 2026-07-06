"""Local control: serve agent commands on this machine's browser or desktop via hai-drivers."""

from .bridge import BridgeBusyError, LocalBridge, session_id_from_environment_id
from .browser import BrowserBridge, ensure_local_chrome
from .desktop import DesktopBridge
from .manager import BridgeManager, ensure_bridges, stop_bridges

__all__ = [
    "BridgeBusyError",
    "BridgeManager",
    "BrowserBridge",
    "DesktopBridge",
    "LocalBridge",
    "ensure_bridges",
    "ensure_local_chrome",
    "session_id_from_environment_id",
    "stop_bridges",
]

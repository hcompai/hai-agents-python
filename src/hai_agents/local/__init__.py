"""Local control: serve agent commands on this machine's browser or desktop via hai-drivers."""

from .bridge import LocalBridge
from .browser import SeleniumBrowserBridge
from .desktop import PyautoguiDesktopBridge
from .errors import BridgeBusyError
from .manager import BridgeManager, ensure_bridges, stop_bridges
from .utils import session_id_from_environment_id

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

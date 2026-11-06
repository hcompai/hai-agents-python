"""HoloTab for a holotab environment: the hub registered with Chrome, and this process's client connected to it."""

from __future__ import annotations

import logging
import threading

from ..bridge import TokenSource, resolve_token
from .bridge import DEFAULT_CLIENT, NOT_CONNECTED, install_host, process_client

logger = logging.getLogger(__name__)

PROBE_WAIT_S = 2.0
FIRST_USE_WAIT_S = 65.0

_lock = threading.Lock()


def require_holotab(api_key: TokenSource, client: str = DEFAULT_CLIENT) -> None:
    """Registers the hub, starts the process client for the app ``client``, and waits for it to connect; raises with
    the reason otherwise.

    HoloTab starts its native host from a one-minute alarm, so after a quick look the wait covers that alarm
    (``FIRST_USE_WAIT_S``) and says so.
    """
    holotab = process_client(client, resolve_token(api_key))
    with _lock:
        if holotab.connected:
            return
        try:
            install_host()
            holotab.start()
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(f"HoloTab cannot reach this process: {exc}") from exc
    if not holotab.wait_connected(PROBE_WAIT_S) and not holotab.incompatible:
        logger.warning("Waiting up to %ds for HoloTab to connect to this process", FIRST_USE_WAIT_S)
        holotab.wait_connected(FIRST_USE_WAIT_S - PROBE_WAIT_S)
    if not holotab.connected:
        raise RuntimeError(holotab.incompatible or NOT_CONNECTED)

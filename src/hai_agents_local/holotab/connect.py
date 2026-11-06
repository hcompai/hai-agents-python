"""Whether HoloTab can drive this user's Chrome right now."""

from __future__ import annotations

import logging
import threading
import time

from . import install
from .link import process_link

logger = logging.getLogger(__name__)

PROBE_WAIT_S = 2.0
FIRST_USE_WAIT_S = 65.0
NEGATIVE_TTL_S = 30.0

_lock = threading.Lock()
_failed_at: float | None = None
_first_use_until = 0.0


def holotab_connected() -> bool:
    """Installs the native host if Chrome has none, listens, and reports whether the extension said HELLO.

    A host manifest written just now waits for HoloTab's retry alarm (up to ``FIRST_USE_WAIT_S``); otherwise the probe
    waits briefly. A miss is remembered for ``NEGATIVE_TTL_S`` so each session does not pay the wait again.
    """
    global _failed_at, _first_use_until
    with _lock:
        link = process_link()
        if link.connected:
            return True
        now = time.monotonic()
        if _failed_at is not None and now - _failed_at < NEGATIVE_TTL_S:
            return False
        fresh = not install.host_registered()
        if fresh:
            _first_use_until = now + FIRST_USE_WAIT_S
        try:
            install.install_host()
            link.start()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.info("HoloTab is not available: %s", exc)
            _failed_at = now
            return False
        wait_s = FIRST_USE_WAIT_S if fresh else max(_first_use_until - now, PROBE_WAIT_S)
    found = link.wait_connected(wait_s)
    with _lock:
        _failed_at = None if found else time.monotonic()
    return found

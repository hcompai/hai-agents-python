"""Out-of-band kill switch: a cross-process stop file, plus a global double-Esc listener on macOS.

Ctrl-C is not a reliable panic button while an agent drives the mouse and keyboard: the terminal
may not have focus, and focus itself is what the agent is fighting you for. The stop file works
from any terminal (`hai local stop`); the Esc listener works from anywhere at all.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

STOP_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "hai" / "stop"
STOP_POLL_S = 0.25
STOP_KEY_TAPS = 2
STOP_KEY_WINDOW_S = 0.6
# Carbon virtual key code for Esc; stable across keyboard layouts.
ESC_KEYCODE = 53
TAP_START_TIMEOUT_S = 2.0
TAP_STOP_JOIN_TIMEOUT_S = 2.0

KILL_SWITCH_ARMED_HINT = "kill switch armed: press Esc twice fast to stop"
KILL_SWITCH_UNAVAILABLE_HINT = (
    "double-Esc kill switch unavailable; grant Input Monitoring to this terminal in "
    "System Settings -> Privacy & Security, or stop with `hai local stop`"
)


def request_stop(now: float | None = None) -> None:
    """File a stop request for any in-flight local turn on this machine."""
    STOP_PATH.parent.mkdir(parents=True, exist_ok=True)
    STOP_PATH.write_text(str(now if now is not None else time.time()), encoding="utf-8")


class StopSentinel:
    """Reads the shared stop file; only stops filed after ``started_at`` count, so stale files are inert."""

    def __init__(self, started_at: float) -> None:
        self._started_at = started_at

    def stop_requested(self) -> bool:
        # Total by design: an unreadable or malformed channel reads as "no stop", never a crash.
        try:
            requested_at = float(STOP_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return requested_at > self._started_at


class StopWatcher:
    """Daemon thread polling the stop channel; runs ``on_stop`` once when a stop is filed, then ends."""

    def __init__(self, on_stop: Callable[[], None]) -> None:
        self._sentinel = StopSentinel(time.time())
        self._on_stop = on_stop
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True, name="hai-stop-watcher")
        self._thread.start()

    @property
    def active(self) -> bool:
        return not self._done.is_set()

    def _poll(self) -> None:
        while not self._done.wait(STOP_POLL_S):
            if self._sentinel.stop_requested():
                self._done.set()
                try:
                    self._on_stop()
                except Exception:
                    logger.exception("kill-switch stop handler failed")

    def stop(self) -> None:
        self._done.set()


class MultiTapDetector:
    """Fires once when ``taps`` timestamps fall within ``window_s`` of each other, then resets."""

    def __init__(self, taps: int = STOP_KEY_TAPS, window_s: float = STOP_KEY_WINDOW_S) -> None:
        self._taps = taps
        self._window_s = window_s
        self._times: list[float] = []

    def record(self, t: float) -> bool:
        self._times = [seen for seen in self._times if t - seen <= self._window_s]
        self._times.append(t)
        if len(self._times) >= self._taps:
            self._times.clear()
            return True
        return False


class QuartzEscTap:
    """Listen-only global Esc tap on macOS that files a stop on a rapid double-Esc.

    The tap re-enables itself when macOS disables it: a heavy desktop turn floods the session with
    synthetic input, listen-only taps fall behind the watchdog budget, and the OS switches them off
    exactly when the panic button matters most.
    """

    def __init__(self) -> None:
        self._detector = MultiTapDetector()
        self._ready = threading.Event()
        self._armed = False
        self._quartz: Any = None
        self._tap: Any = None
        self._loop: Any = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Arm the tap on its own run-loop thread; False when Quartz or the Input Monitoring grant is missing."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="hai-esc-tap")
        self._thread.start()
        self._ready.wait(timeout=TAP_START_TIMEOUT_S)
        return self._armed

    def stop(self) -> None:
        if self._quartz is not None and self._loop is not None:
            self._quartz.CFRunLoopStop(self._loop)
        if self._thread is not None:
            self._thread.join(timeout=TAP_STOP_JOIN_TIMEOUT_S)
        self._thread = None
        self._loop = None

    def _run(self) -> None:
        try:
            import Quartz
        except Exception:
            logger.debug("Quartz is unavailable; the Esc kill switch is disabled")
            self._ready.set()
            return
        self._quartz = Quartz
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
            self._handler,
            None,
        )
        if tap is None:
            logger.debug("could not create the Esc event tap (Input Monitoring not granted?)")
            self._ready.set()
            return
        self._tap = tap
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)
        self._armed = True
        self._ready.set()
        Quartz.CFRunLoopRun()

    def _handler(self, proxy: Any, event_type: int, event: Any, refcon: Any) -> Any:
        quartz = self._quartz
        try:
            if event_type in (quartz.kCGEventTapDisabledByTimeout, quartz.kCGEventTapDisabledByUserInput):
                quartz.CGEventTapEnable(self._tap, True)
                logger.warning("macOS disabled the Esc kill-switch tap; re-enabled it")
            elif (
                event_type == quartz.kCGEventKeyDown
                and quartz.CGEventGetIntegerValueField(event, quartz.kCGKeyboardEventKeycode) == ESC_KEYCODE
                and self._detector.record(time.monotonic())
            ):
                logger.warning("double-Esc detected; requesting stop")
                request_stop()
        except Exception:
            logger.warning("Esc kill-switch handler failed", exc_info=True)
        return event


def arm_esc_listener() -> QuartzEscTap | None:
    """Arm the global double-Esc listener; None when unsupported here (non-macOS) or not permitted."""
    import sys

    if sys.platform != "darwin":
        return None
    tap = QuartzEscTap()
    return tap if tap.start() else None

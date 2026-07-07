from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import os
import sys
import threading
from typing import Sequence

from .bridge import BridgeBusyError, LocalBridge

logger = logging.getLogger(__name__)

AUTO_BRIDGE_ENV_VAR = "HAI_AUTO_BRIDGE"

STOP_JOIN_TIMEOUT_S = 5.0
READY_TIMEOUT_S = 60.0


def auto_bridges_enabled() -> bool:
    """Read at each session creation; local bridges auto-start unless set to 0/false/no."""
    return os.getenv(AUTO_BRIDGE_ENV_VAR, "1").strip().lower() not in {"0", "false", "no"}


class BridgeManager:
    """Runs each bridge on a daemon thread; at most one bridge per environment kind per process."""

    def __init__(self) -> None:
        self._runners: dict[str, _Runner] = {}
        self._lock = threading.Lock()

    def ensure(self, bridges: Sequence[LocalBridge]) -> list[str]:
        """Start any bridges not already running; returns the session ids of newly started ones."""
        started: list[str] = []
        try:
            for bridge in bridges:
                if self._ensure_one(bridge):
                    started.append(bridge.session_id)
        except BaseException:
            self.stop(started)
            raise
        return started

    def _ensure_one(self, bridge: LocalBridge) -> bool:
        with self._lock:
            runner = self._runners.get(bridge.session_id)
            started = runner is None or not runner.thread.is_alive()
            if started:
                if any(
                    other.bridge.environment_kind == bridge.environment_kind and other.thread.is_alive()
                    for other in self._runners.values()
                ):
                    raise RuntimeError(
                        f"this machine already serves a local {bridge.environment_kind} environment; "
                        f"cannot also serve {bridge.environment_id!r}"
                    )
                logger.info(
                    "starting local %s bridge for environment %r", bridge.environment_kind, bridge.environment_id
                )
                runner = _Runner(bridge)
                self._runners[bridge.session_id] = runner
        try:
            if not runner.bridge.ready.wait(READY_TIMEOUT_S):
                raise RuntimeError(
                    f"local {bridge.environment_kind} bridge for environment {bridge.environment_id!r} "
                    f"was not ready after {READY_TIMEOUT_S:.0f}s"
                )
            if runner.error is not None:
                raise RuntimeError(
                    f"local {bridge.environment_kind} bridge for environment {bridge.environment_id!r} failed to start"
                ) from runner.error
        except BaseException:
            if started:
                with self._lock:
                    if self._runners.get(bridge.session_id) is runner:
                        del self._runners[bridge.session_id]
                runner.stop()
            raise
        return started

    def stop(self, session_ids: Sequence[str]) -> None:
        with self._lock:
            stopping = [self._runners.pop(sid) for sid in session_ids if sid in self._runners]
        for runner in stopping:
            runner.stop()

    def stop_all(self) -> None:
        with self._lock:
            stopping = list(self._runners.values())
            self._runners.clear()
        for runner in stopping:
            runner.stop()


class _Runner:
    def __init__(self, bridge: LocalBridge) -> None:
        self.bridge = bridge
        self.error: BaseException | None = None
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._serve, daemon=True, name=f"hai-bridge-{bridge.environment_kind}")
        self.thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.bridge.run())
        except BridgeBusyError:
            logger.info(
                "a bridge for environment %r already runs on this machine; reusing it", self.bridge.environment_id
            )
        except Exception as exc:
            self.error = exc
            if not sys.is_finalizing() and threading.main_thread().is_alive():
                logger.exception("local %s bridge crashed", self.bridge.environment_kind)
        finally:
            self.bridge.ready.set()
            self.loop.close()

    def stop(self) -> None:
        with contextlib.suppress(RuntimeError):
            self.loop.call_soon_threadsafe(self.bridge.request_stop)
        self.thread.join(timeout=STOP_JOIN_TIMEOUT_S)


_default_manager = BridgeManager()


def ensure_bridges(bridges: Sequence[LocalBridge]) -> list[str]:
    return _default_manager.ensure(bridges)


def stop_bridges(session_ids: Sequence[str] | None = None) -> None:
    if session_ids is None:
        _default_manager.stop_all()
    else:
        _default_manager.stop(session_ids)


atexit.register(stop_bridges)

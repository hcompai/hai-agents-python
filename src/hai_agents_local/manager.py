from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import sys
import threading
from typing import Sequence

from .bridge import LocalBridge

logger = logging.getLogger(__name__)

STOP_JOIN_TIMEOUT_S = 5.0
READY_TIMEOUT_S = 60.0


class BridgeManager:
    """Runs each bridge on a daemon thread, at most one per environment kind."""

    def __init__(self) -> None:
        self._runners: dict[str, _Runner] = {}
        self._lock = threading.Lock()

    def ensure(self, bridges: Sequence[LocalBridge]) -> list[str]:
        """Start any bridges not already running; returns the session ids of newly started ones."""
        kinds = [bridge.environment_kind for bridge in bridges]
        for kind in kinds:
            if kinds.count(kind) > 1:
                raise RuntimeError(f"cannot serve two local {kind} environments from one machine")
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
        displaced: list[_Runner] = []
        with self._lock:
            runner = self._runners.get(bridge.session_id)
            started = runner is None or not runner.thread.is_alive()
            if started:
                displaced = self._displace_kind_locked(bridge)
                logger.info(
                    "starting local %s bridge for environment %r", bridge.environment_kind, bridge.environment_id
                )
                runner = _Runner(bridge)
                self._runners[bridge.session_id] = runner
        for other in displaced:
            other.stop()
            other.notify_lost()
        try:
            if not runner.bridge.ready.wait(READY_TIMEOUT_S):
                hint = f" ({bridge.startup_hint})" if bridge.startup_hint is not None else ""
                raise RuntimeError(
                    f"local {bridge.environment_kind} bridge for environment {bridge.environment_id!r} "
                    f"was not ready after {READY_TIMEOUT_S:.0f}s{hint}"
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

    def _displace_kind_locked(self, bridge: LocalBridge) -> list[_Runner]:
        """One driver per kind: a machine has one desktop and one debuggable Chrome, so the newest
        session takes the bridge over from any previous session still holding it. Returns the
        displaced runners; the caller stops them and fires their loss handlers off the lock,
        since a stopping runner's own loss handler may need this lock."""
        displaced: list[_Runner] = []
        for sid, other in list(self._runners.items()):
            if other.bridge.environment_kind != bridge.environment_kind:
                continue
            if other.thread.is_alive():
                logger.warning(
                    "stopping the local %s bridge for session %s to serve session %s",
                    bridge.environment_kind,
                    other.bridge.session_id,
                    bridge.session_id,
                )
            del self._runners[sid]
            displaced.append(other)
        return displaced

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
        # A restarted bridge keeps its ready event from the previous run; the wait below must see this run's.
        bridge.ready.clear()
        self.thread = threading.Thread(target=self._serve, daemon=True, name=f"hai-bridge-{bridge.environment_kind}")
        self.thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.bridge.run())
            if not self.bridge.ready.is_set():
                # Stopped mid-setup (e.g. displaced during channel retry backoff): the finally
                # below unblocks ensure(), which must see a failure, not a serving bridge.
                self.error = RuntimeError("bridge was stopped before it became ready")
        except Exception as exc:
            self.error = exc
            if not sys.is_finalizing() and threading.main_thread().is_alive():
                logger.exception("local %s bridge crashed", self.bridge.environment_kind)
                self.notify_lost()
        finally:
            self.bridge.ready.set()
            self.loop.close()

    def notify_lost(self) -> None:
        """Fires the bridge's loss handler once, on crash or displacement after a successful
        startup; startup failures surface to the ensure() caller instead."""
        handler, self.bridge.on_crash = self.bridge.on_crash, None
        if handler is not None and self.bridge.ready.is_set():
            try:
                handler()
            except Exception:
                logger.exception("bridge loss handler failed")

    def stop(self) -> None:
        with contextlib.suppress(RuntimeError):
            self.loop.call_soon_threadsafe(self.bridge.request_stop)
        # A bridge's loss handler runs on its own runner thread; a thread cannot join itself.
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=STOP_JOIN_TIMEOUT_S)


# Process-wide manager behind ensure_bridges/stop_bridges; cleaned up at interpreter exit.
_default_manager = BridgeManager()
atexit.register(_default_manager.stop_all)


def ensure_bridges(bridges: Sequence[LocalBridge]) -> list[str]:
    return _default_manager.ensure(bridges)


def stop_bridges(session_ids: Sequence[str] | None = None) -> None:
    if session_ids is None:
        _default_manager.stop_all()
    else:
        _default_manager.stop(session_ids)

"""Message the agent while a turn runs: typing goes into the pinned input box, enter sends, esc pauses."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from rich.console import Console

from hai_agents import is_settled_session_status, is_terminal_session_status
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage

from . import keys, ui

ANSWER = "/answer"
_POLL_S = 0.5


def _in_thread(work: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=work, daemon=True, name="hai-steer")
    thread.start()
    return thread


@dataclass
class Steering:
    """A message pauses the agent and lands once the pause does, then resumes it.

    A pause drops a model call in flight, so the agent cannot answer past a message it has not read.
    """

    client: Any
    session_id: str
    feed: ui.StepFeed
    out: Console
    local_command: Callable[[str], bool] = lambda text: False
    spawn: Callable[[Callable[[], None]], Any] = _in_thread
    box: ui.InputBox = field(default_factory=ui.InputBox)
    pending: str | None = None
    pending_shown: bool = False
    _pause: Literal["pausing", "paused"] | None = None
    _queued: list[str] = field(default_factory=list)
    _done: threading.Event = field(default_factory=threading.Event)
    _lander: Any = None
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self.feed.box = self.box
        self._show()

    def watch(self) -> keys.EscWatcher:
        return keys.EscWatcher(self.on_esc, self.on_keys)

    def finish(self) -> None:
        """The stream ended; wait for a pause in flight to settle so it cannot freeze the next turn."""
        self._done.set()
        if self._lander is not None and hasattr(self._lander, "join"):
            self._lander.join()

    def on_keys(self, typed: str) -> None:
        text, sent = keys.edit(self.box.text, typed)
        self.box.text = "" if sent else text
        if sent and text.strip():
            self.submit(text.strip())

    def on_esc(self) -> None:
        with self._lock:
            if self._done.is_set() or self._pause == "pausing":
                return
            if self._pause == "paused":
                self._release()
            else:
                self._request_pause()

    def submit(self, text: str) -> None:
        if self.local_command(text):
            return
        with self._lock:
            if self._done.is_set():
                self.pending, self.pending_shown = text, False
                return
            self.feed.note(text)
            self._queued.append(text)
            if self._pause is None:
                self._request_pause()
            elif self._pause == "paused":
                self._release()

    def _request_pause(self) -> None:
        self._pause = "pausing"
        self._show()
        self._lander = self.spawn(self._land)

    def _land(self) -> None:
        try:
            self._await_start()
            self.client.sessions.pause_session(self.session_id)
        except Exception as exc:
            ui.error(self.out, f"could not pause: {exc}")
            with self._lock:
                self._release(resume=False)
            return
        try:
            status = self._await_pause()
        except Exception as exc:
            ui.error(self.out, str(exc))
            status = None
        with self._lock:
            if status == "paused" and not self._done.is_set():
                if self._queued:
                    self._release()
                else:
                    self._pause = "paused"
                    self._show()
                return
            if status is None or not is_terminal_session_status(status):
                self._resume()
            texts = [text for text in self._queued if text != ANSWER]
            if texts:
                self.pending, self.pending_shown = "\n".join(texts), True
            self._queued.clear()
            self._pause = None
            self._show()

    def _await_start(self) -> None:
        """A pause sent while the agent boots is dropped."""
        while not self._done.is_set():
            if str(self.client.sessions.get_session_status(self.session_id).status) not in ("queued", "pending"):
                return
            time.sleep(_POLL_S)

    def _await_pause(self) -> str | None:
        """A pause lands at the end of the current step; a message sent before then is overtaken by it."""
        while True:
            status = str(self.client.sessions.get_session_status(self.session_id).status)
            if status in ("paused", "awaiting_tool_results") or is_settled_session_status(status):
                return status
            if self._done.is_set():
                return None
            time.sleep(_POLL_S)

    def _release(self, *, resume: bool = True) -> None:
        """Send what was typed, then resume; resume even if sending fails, or the paused turn never settles."""
        texts, self._queued = self._queued, []
        message = "\n".join(text for text in texts if text != ANSWER)
        if message:
            try:
                request = SendSessionMessagesRequestBody_UserMessage(message=message)
                self.client.sessions.send_session_messages(self.session_id, request=request)
            except Exception as exc:
                ui.error(self.out, f"message not sent: {exc}")
        if ANSWER in texts:
            self._force_answer()
        elif resume:
            self._resume()
        self._pause = None
        self._show()

    def _force_answer(self) -> None:
        """Asking for the answer also unpauses the session."""
        try:
            self.client.sessions.force_session_answer(self.session_id)
        except Exception as exc:
            ui.error(self.out, f"could not ask for the answer: {exc}")
            self._resume()

    def _resume(self) -> None:
        try:
            self.client.sessions.resume_session(self.session_id)
        except Exception as exc:
            ui.error(self.out, f"could not resume: {exc}", fix="ctrl+c cancels the turn")

    def _show(self) -> None:
        box = self.box
        if self._pause == "paused":
            box.placeholder = "What should it do instead?"
            box.hint, box.hint_style = f"paused {ui.SEP} enter sends and resumes {ui.SEP} esc resumes", "warn"
        elif self._pause == "pausing":
            box.placeholder = "Type to message the agent"
            box.hint, box.hint_style = "pausing after this step…", "warn"
        else:
            box.placeholder = "Type to message the agent"
            box.hint, box.hint_style = f"enter sends {ui.SEP} esc pauses {ui.SEP} ctrl+c stops", "meta"

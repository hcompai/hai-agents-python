from __future__ import annotations

import os
import pty
import sys
import threading
import time

import pytest

from hai_agents_cli import keys


@pytest.mark.skipif(sys.platform == "win32", reason="no pty")
@pytest.mark.parametrize("interrupted", [False, True])
def test_esc_watcher_exits_promptly_and_restores_the_terminal(monkeypatch, interrupted) -> None:
    import termios

    leader, follower = pty.openpty()
    monkeypatch.setattr(sys, "stdin", os.fdopen(follower, "r"))
    modes = termios.ICANON | termios.ECHO
    saved = termios.tcgetattr(follower)[3] & modes

    def leave() -> None:
        with keys.EscWatcher(lambda: None):
            if interrupted:
                raise KeyboardInterrupt

    thread = threading.Thread(target=lambda: pytest.raises(KeyboardInterrupt, leave) if interrupted else leave())
    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert termios.tcgetattr(follower)[3] & modes == saved
    os.close(leader)


@pytest.mark.skipif(sys.platform == "win32", reason="no pty")
def test_typed_keys_edit_one_line_across_reads_and_a_lone_esc_pauses(monkeypatch) -> None:
    leader, follower = pty.openpty()
    monkeypatch.setattr(sys, "stdin", os.fdopen(follower, "r"))
    box = {"text": "", "sent": [], "escs": 0}

    def on_keys(typed: str) -> None:
        box["text"], sent = keys.edit(box["text"], typed)
        if sent:
            box["sent"].append(box["text"])

    def on_esc() -> None:
        box["escs"] += 1

    with keys.EscWatcher(on_esc, on_keys):
        for chunk in (b"o", b"\x7fhi there\x17you\r", b"\x1b"):
            os.write(leader, chunk)
            time.sleep(0.3)
    os.close(leader)

    assert (box["sent"], box["escs"]) == (["hi you"], 1)

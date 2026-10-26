from __future__ import annotations

import os
import pty
import sys
import threading

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
        with keys.EscWatcher(lambda watcher: None):
            if interrupted:
                raise KeyboardInterrupt

    thread = threading.Thread(target=lambda: pytest.raises(KeyboardInterrupt, leave) if interrupted else leave())
    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert termios.tcgetattr(follower)[3] & modes == saved
    os.close(leader)

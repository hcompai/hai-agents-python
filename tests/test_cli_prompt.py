import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from hai_agents_cli.prompt import Prompt

ENTER, CTRL_C, CTRL_D, TAB, UP, DOWN = "\r", "\x03", "\x04", "\t", "\x1b[A", "\x1b[B"


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (f"{ENTER}{ENTER}hi{ENTER}", "hi"),
        (f"draft{CTRL_C}hi{ENTER}", "hi"),
        (f"{CTRL_C}{CTRL_C}", None),
        (CTRL_D, None),
        (f"/n{ENTER}", "/new"),
        (f"/{DOWN}{ENTER}", "/exit"),
        (f"/n{TAB}flights{ENTER}", "/new flights"),
        (f"/new find flights{ENTER}", "/new find flights"),
        (f"one\\{ENTER}two{ENTER}", "one\ntwo"),
        ("?", "?"),
    ],
)
def test_prompt_keys(monkeypatch, tmp_path, keys, expected) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(keys)
        prompt = Prompt(tmp_path / "history", lambda: [("/new [task]", "start fresh"), ("/exit", "leave")])
        assert prompt.read(toolbar=lambda: "", placeholder="") == expected


def test_up_scrolls_history_past_a_recalled_command(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    history = FileHistory(str(tmp_path / "history"))
    history.store_string("find flights")
    history.store_string("/exit")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(f"{UP}{UP}{ENTER}")
        prompt = Prompt(tmp_path / "history", lambda: [("/new [task]", "start fresh"), ("/exit", "leave")])
        assert prompt.read(toolbar=lambda: "", placeholder="") == "find flights"

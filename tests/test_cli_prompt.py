import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from hai_agents_cli.prompt import Prompt

ENTER, CTRL_C, CTRL_D, TAB, DOWN = "\r", "\x03", "\x04", "\t", "\x1b[B"


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

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from hai_agents_cli.prompt import Prompt, choose

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


@pytest.mark.parametrize("keys", [f"{UP}{UP}{ENTER}", f"\x12flig{ENTER}{ENTER}"])
def test_history_is_reachable_past_a_recalled_command(monkeypatch, tmp_path, keys) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    history = FileHistory(str(tmp_path / "history"))
    history.store_string("find flights")
    history.store_string("/exit")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(keys)
        prompt = Prompt(tmp_path / "history", lambda: [("/new [task]", "start fresh"), ("/exit", "leave")])
        assert prompt.read(toolbar=lambda: "", placeholder="") == "find flights"


@pytest.mark.parametrize(("keys", "expected"), [(f"fi{TAB}{ENTER}", "find flights"), (f"{TAB}{ENTER}", "Book a table")])
def test_tab_accepts_the_grey_suggestion(monkeypatch, tmp_path, keys, expected) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    FileHistory(str(tmp_path / "history")).store_string("find flights")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(keys)
        prompt = Prompt(tmp_path / "history", lambda: [("/exit", "leave")])
        assert prompt.read(toolbar=lambda: "", placeholder='Try "Book a table"', example="Book a table") == expected


@pytest.mark.parametrize(
    ("keys", "expected"), [(ENTER, 1), (f"{DOWN}{DOWN}{ENTER}", 0), (f"{UP}{ENTER}", 0), (CTRL_C, None)]
)
def test_picker_moves_with_the_arrows_and_wraps(monkeypatch, keys, expected) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(keys)
        assert choose([("a", ""), ("b", ""), ("c", "")], {0: "Letters"}, current=1) == expected

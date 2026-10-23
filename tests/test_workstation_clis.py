"""The workstation extra puts the three CLIs the bridge hands the agent next to `desk`, and each one answers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sysconfig

import pytest

pytest.importorskip("hai_drivers.code_sandbox.local.driver")

SCRIPTS = os.pathsep.join([sysconfig.get_path("scripts"), os.environ.get("PATH", os.defpath)])


def cli(name: str) -> str:
    found = shutil.which(name, path=SCRIPTS)
    assert found, f"{name} is not installed next to the interpreter; pip install 'hai-agents[workstation]'"
    return found


def test_the_bridge_finds_desk_cua_and_web_in_one_directory() -> None:
    desk = cli("desk")
    assert {os.path.dirname(cli("cua")), os.path.dirname(cli("web"))} == {os.path.dirname(desk)}


@pytest.mark.parametrize(
    ("argv", "expect"),
    [
        (["desk", "aliases"], "installed="),
        (["cua", "--help"], "windows"),
        (["cua", "skill"], "cua"),
        (["web", "--help"], "snap"),
    ],
)
def test_each_cli_answers_without_a_display(argv: list[str], expect: str) -> None:
    done = subprocess.run(
        [cli(argv[0]), *argv[1:]], capture_output=True, text=True, timeout=60, env={**os.environ, "DISPLAY": ""}
    )
    assert done.returncode == 0, done.stderr
    assert expect in done.stdout

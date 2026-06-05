from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.integration
def test_cli_help_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "hai_agents_extras.cli", "--help"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "hai-agents" in result.stdout


@pytest.mark.integration
def test_cli_live_run(api_key: str, base_url: str) -> None:
    env = {
        **os.environ,
        "HAI_API_KEY": api_key,
        "HAI_API_BASE_URL": base_url,
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hai_agents_extras.cli",
            "--json",
            "run",
            "Reply with exactly: hello",
            "--max-steps",
            "3",
            "--max-time",
            "60",
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "session_id" in result.stdout

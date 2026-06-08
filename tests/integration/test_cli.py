from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


@pytest.mark.integration
def test_cli_help_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "hai_agents_cli", "--help"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "hai" in result.stdout


@pytest.mark.integration
def test_cli_live_run(api_key: str, base_url: str, created_sessions: list[str]) -> None:
    env = {
        **os.environ,
        "HAI_API_KEY": api_key,
        "HAI_API_BASE_URL": base_url,
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hai_agents_cli",
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
    payload = json.loads(result.stdout)
    created_sessions.append(payload["session_id"])
    assert payload["session_id"]
    assert payload["status"] in {"completed", "failed", "timed_out", "interrupted"}

"""Offline smoke checks: the package imports, clients construct, models parse."""

from __future__ import annotations

from hai_agents import AsyncClient, Client, SessionStatus


def test_clients_construct_and_expose_resources() -> None:
    client = Client(api_key="hk-smoke", base_url="http://x")
    AsyncClient(api_key="hk-smoke", base_url="http://x")
    for resource in ("sessions", "agents", "skills", "environments"):
        assert hasattr(client, resource), f"missing resource namespace: {resource}"


def test_core_model_round_trips() -> None:
    status = SessionStatus.model_validate({"status": "completed", "steps": 3})
    assert status.status == "completed"
    assert status.steps == 3
    assert status.model_dump(exclude_none=True)["status"] == "completed"


def test_base_import_never_loads_local_mode() -> None:
    """Remote-only users must not pay for process/download machinery at import."""
    import subprocess
    import sys

    code = (
        "import sys, hai_agents; "
        "loaded = sorted(m for m in sys.modules if m.startswith('hai_agents.local')); "
        "assert not loaded, loaded"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

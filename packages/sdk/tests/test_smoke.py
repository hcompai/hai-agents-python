"""Offline smoke checks: the package imports, clients construct, models parse."""

from __future__ import annotations

from hai_agents import AsyncClient, Client, SessionStatus


def test_clients_construct_and_expose_resources() -> None:
    client = Client(token="hk-smoke", base_url="http://x")
    AsyncClient(token="hk-smoke", base_url="http://x")
    for resource in ("sessions", "agents", "skills", "environments"):
        assert hasattr(client, resource), f"missing resource namespace: {resource}"


def test_core_model_round_trips() -> None:
    status = SessionStatus.model_validate({"status": "completed", "steps": 3})
    assert status.status == "completed"
    assert status.steps == 3
    assert status.model_dump(exclude_none=True)["status"] == "completed"

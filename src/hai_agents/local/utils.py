"""Helpers shared across the local bridge stack."""

import uuid


def session_id_from_environment_id(environment_id: str, api_key: str, environment_kind: str) -> str:
    """Deterministic routing id: every process using the same key serves the same session."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{api_key}.{environment_id}.{environment_kind}"))

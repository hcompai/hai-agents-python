"""Cheapest possible auth check: hit /sessions/quota and confirm a typed
response comes back. A 401/403 raises ApiError (wrong key); a 200 means auth +
base_url + the SDK's response parsing all work. Runs in well under a second, so
it's a good gate before the heavier tests.
"""

from __future__ import annotations

import pytest

from hai_agents import Client

pytestmark = pytest.mark.integration


def test_quota_endpoint_authenticates(client: Client) -> None:
    quota = client.sessions.get_session_quota()
    assert quota.limit > 0
    assert quota.active >= 0
    assert quota.available == quota.limit - quota.active

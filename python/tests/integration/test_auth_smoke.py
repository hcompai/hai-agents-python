"""Cheapest possible auth check: hit /sessions/quota and confirm a typed
response comes back. A 401/403 here means the test key is wrong; a 200 means
auth + base_url + the SDK's response parsing all work. Runs in well under a
second, so it's a good gate before the heavier tests.
"""

from __future__ import annotations

import pytest

from agent_platform import Client
from agent_platform.api.sessions import get_session_quota as get_quota

pytestmark = pytest.mark.integration


def test_quota_endpoint_authenticates(client: Client) -> None:
    resp = get_quota.sync_detailed(client=client)
    assert resp.status_code == 200, (
        f"expected 200 from /sessions/quota, got {resp.status_code}. Body: {resp.content[:300]!r}"
    )
    quota = resp.parsed
    assert quota is not None
    assert quota.limit > 0
    assert quota.active >= 0
    assert quota.available == quota.limit - quota.active

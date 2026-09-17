"""Unit tests for ``verify_webhook``: HMAC, replay window, secret rotation, raw body.

The helper is a public README surface (PR #94) with no prior coverage. These
tests lock the documented contract without changing the implementation.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from hai_agents.webhook_verification import (
    DEFAULT_TOLERANCE_S,
    WebhookEventData,
    WebhookVerificationError,
    verify_webhook,
)

SECRET = "whsec_test"
OLD_SECRET = "whsec_old"
NEW_SECRET = "whsec_new"
NOW = 1_700_000_000
TIMESTAMP = str(NOW)

PAYLOAD = {
    "type": "session.status_updated",
    "id": "evt_1",
    "created_at": "2023-11-14T22:13:20Z",
    "data": {"session_id": "sess_1", "status": "idle", "previous_status": "running"},
}
BODY = json.dumps(PAYLOAD, separators=(",", ":")).encode()


def _sign(secret: str, timestamp: str, raw: bytes) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture(autouse=True)
def freeze_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hai_agents.webhook_verification.time.time", lambda: float(NOW))


def test_valid_hmac_parses_event() -> None:
    event = verify_webhook(BODY, _sign(SECRET, TIMESTAMP, BODY), TIMESTAMP, SECRET)
    assert event.type == "session.status_updated"
    assert event.id == "evt_1"
    assert event.data["session_id"] == "sess_1"
    typed = WebhookEventData.model_validate(event.data)
    assert typed.status == "idle"
    assert typed.previous_status == "running"


def test_str_body_matches_bytes_body() -> None:
    raw_str = BODY.decode()
    event = verify_webhook(raw_str, _sign(SECRET, TIMESTAMP, BODY), TIMESTAMP, SECRET)
    assert event.id == "evt_1"


def test_bad_hmac_is_rejected() -> None:
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(BODY, _sign("whsec_other", TIMESTAMP, BODY), TIMESTAMP, SECRET)


def test_empty_signature_is_rejected() -> None:
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(BODY, "", TIMESTAMP, SECRET)


def test_replay_older_than_300s_is_rejected() -> None:
    stale = str(NOW - DEFAULT_TOLERANCE_S - 1)
    with pytest.raises(WebhookVerificationError, match="possible replay"):
        verify_webhook(BODY, _sign(SECRET, stale, BODY), stale, SECRET)


def test_future_timestamp_beyond_300s_is_rejected() -> None:
    ahead = str(NOW + DEFAULT_TOLERANCE_S + 1)
    with pytest.raises(WebhookVerificationError, match="possible replay"):
        verify_webhook(BODY, _sign(SECRET, ahead, BODY), ahead, SECRET)


def test_timestamp_exactly_at_300s_is_accepted() -> None:
    edge = str(NOW - DEFAULT_TOLERANCE_S)
    event = verify_webhook(BODY, _sign(SECRET, edge, BODY), edge, SECRET)
    assert event.id == "evt_1"


def test_invalid_timestamp_is_rejected() -> None:
    with pytest.raises(WebhookVerificationError, match="invalid timestamp header"):
        verify_webhook(BODY, _sign(SECRET, "not-an-int", BODY), "not-an-int", SECRET)


def test_secret_rotation_accepts_old_or_new() -> None:
    candidates = [OLD_SECRET, NEW_SECRET]
    signed_old = verify_webhook(BODY, _sign(OLD_SECRET, TIMESTAMP, BODY), TIMESTAMP, candidates)
    signed_new = verify_webhook(BODY, _sign(NEW_SECRET, TIMESTAMP, BODY), TIMESTAMP, candidates)
    assert signed_old.id == signed_new.id == "evt_1"


def test_secret_rotation_rejects_unknown_secret() -> None:
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(BODY, _sign("whsec_neither", TIMESTAMP, BODY), TIMESTAMP, [OLD_SECRET, NEW_SECRET])


def test_empty_secret_list_is_rejected() -> None:
    with pytest.raises(WebhookVerificationError, match="no secret provided"):
        verify_webhook(BODY, _sign(SECRET, TIMESTAMP, BODY), TIMESTAMP, [])


def test_mac_covers_raw_body_not_reserialized_json() -> None:
    """Whitespace-equivalent JSON is a different MAC; re-dumping the body must not verify."""
    compact = BODY
    pretty = json.dumps(PAYLOAD, indent=2).encode()
    assert json.loads(compact) == json.loads(pretty)
    assert compact != pretty
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(pretty, _sign(SECRET, TIMESTAMP, compact), TIMESTAMP, SECRET)
    event = verify_webhook(pretty, _sign(SECRET, TIMESTAMP, pretty), TIMESTAMP, SECRET)
    assert event.id == "evt_1"


def test_unparsable_payload_after_valid_mac() -> None:
    raw = b"not-json"
    with pytest.raises(WebhookVerificationError, match="unparsable payload"):
        verify_webhook(raw, _sign(SECRET, TIMESTAMP, raw), TIMESTAMP, SECRET)


def test_envelope_missing_fields_is_unparsable() -> None:
    raw = json.dumps({"type": "session.status_updated"}).encode()
    with pytest.raises(WebhookVerificationError, match="unparsable payload"):
        verify_webhook(raw, _sign(SECRET, TIMESTAMP, raw), TIMESTAMP, SECRET)


def test_unknown_event_type_still_verifies() -> None:
    payload = {**PAYLOAD, "type": "session.something_new"}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    event = verify_webhook(raw, _sign(SECRET, TIMESTAMP, raw), TIMESTAMP, SECRET)
    assert event.type == "session.something_new"
    assert event.data == payload["data"]

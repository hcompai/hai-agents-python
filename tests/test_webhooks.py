"""Webhook verification accepts genuine deliveries and rejects forgeries and replays."""

import hashlib
import hmac
import json
import time

import pytest

from hai_agents import WebhookVerificationError, verify_webhook

SECRET = "whsec_test"


def _delivery(payload: dict, secret: str = SECRET, timestamp: int | None = None):
    body = json.dumps(payload).encode()
    ts = str(timestamp if timestamp is not None else int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"sha256={digest}", ts


EVENT = {
    "type": "session.status_updated",
    "id": "evt_1",
    "created_at": "2026-06-11T12:00:00Z",
    "data": {"session_id": "sess_1", "status": "completed", "previous_status": "running"},
}


def test_valid_delivery_parses_event():
    body, sig, ts = _delivery(EVENT)
    event = verify_webhook(body, sig, ts, SECRET)
    assert event.type == "session.status_updated"
    assert event.data.session_id == "sess_1"
    assert event.data.previous_status == "running"


def test_str_body_verifies_like_bytes():
    body, sig, ts = _delivery(EVENT)
    assert verify_webhook(body.decode(), sig, ts, SECRET).data.status == "completed"


def test_tampered_body_rejected():
    body, sig, ts = _delivery(EVENT)
    tampered = body.replace(b"completed", b"failed")
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(tampered, sig, ts, SECRET)


def test_wrong_secret_rejected():
    body, sig, ts = _delivery(EVENT)
    with pytest.raises(WebhookVerificationError, match="signature mismatch"):
        verify_webhook(body, sig, ts, "whsec_other")


def test_stale_timestamp_rejected():
    body, sig, ts = _delivery(EVENT, timestamp=int(time.time()) - 3600)
    with pytest.raises(WebhookVerificationError, match="replay"):
        verify_webhook(body, sig, ts, SECRET)


def test_signed_null_data_rejected():
    body, sig, ts = _delivery({**EVENT, "data": None})
    with pytest.raises(WebhookVerificationError, match="unparseable payload"):
        verify_webhook(body, sig, ts, SECRET)


def test_garbage_timestamp_rejected():
    body, sig, _ = _delivery(EVENT)
    with pytest.raises(WebhookVerificationError, match="invalid timestamp"):
        verify_webhook(body, sig, "not-a-number", SECRET)

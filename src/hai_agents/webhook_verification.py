"""Webhook receiving: verify the signature and parse the event envelope."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import typing

import pydantic

SIGNATURE_HEADER = "X-H-Webhook-Signature"
TIMESTAMP_HEADER = "X-H-Webhook-Timestamp"
DEFAULT_TOLERANCE_S = 300


class WebhookVerificationError(Exception):
    """The webhook delivery could not be authenticated."""


class WebhookEventData(pydantic.BaseModel):
    """Payload of a ``session.status_updated`` event."""

    session_id: str
    status: str
    previous_status: typing.Optional[str] = None


class WebhookEvent(pydantic.BaseModel):
    """A verified webhook delivery.

    ``data`` is the raw event payload; its shape depends on ``type``. Branch on
    ``type`` and validate the payload with the matching model, e.g.
    ``WebhookEventData.model_validate(event.data)`` for ``session.status_updated``.
    """

    type: str
    id: str
    created_at: str
    data: typing.Dict[str, typing.Any]


def verify_webhook(
    body: typing.Union[bytes, str],
    signature: str,
    timestamp: str,
    secret: str,
    *,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> WebhookEvent:
    """Authenticate a webhook delivery and return the parsed event.

    ``body`` must be the raw request body (never re-serialized JSON); ``signature`` and
    ``timestamp`` come from the ``X-H-Webhook-Signature`` and ``X-H-Webhook-Timestamp``
    headers. Raises :class:`WebhookVerificationError` when the signature is invalid or
    the delivery is older than ``tolerance_s`` seconds. Authentic deliveries of any
    event type return successfully; ``data`` is left untyped so new event types never
    fail an otherwise-valid delivery.
    """
    raw = body.encode() if isinstance(body, str) else body
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        raise WebhookVerificationError("invalid timestamp header") from None
    if abs(time.time() - sent_at) > tolerance_s:
        raise WebhookVerificationError(f"delivery older than {tolerance_s}s; possible replay")
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={digest}", signature or ""):
        raise WebhookVerificationError("signature mismatch")
    try:
        return WebhookEvent.model_validate(json.loads(raw))
    except (json.JSONDecodeError, pydantic.ValidationError) as e:
        raise WebhookVerificationError(f"unparsable payload: {e}") from None

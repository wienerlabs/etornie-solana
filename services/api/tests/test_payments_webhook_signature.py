"""Tests for ``app.payments.service.verify_webhook``.

We construct real Stripe-Signature headers with the same algorithm
Stripe uses (HMAC-SHA256 over ``timestamp.payload``), then feed them
through the production verifier. Nothing is mocked — the verifier
either accepts a correctly-signed payload or rejects a tampered one
exactly like it would in production.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.config import settings
from app.payments.service import StripeServiceError, verify_webhook


def _sign_payload(payload: bytes, secret: str, *, timestamp: int | None = None) -> str:
    """Reproduce Stripe's ``Stripe-Signature`` header construction.

    Stripe's official scheme (v1): ``HMAC_SHA256(secret, "<ts>.<payload>")``,
    with the header serialised as ``t=<ts>,v1=<signature>``. This is
    the same code Stripe's SDK uses to verify our header on the way
    in — so a matching ``v1`` here proves the SDK will accept it.
    """
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={sig}"


def _make_event_payload(event_type: str = "checkout.session.completed") -> bytes:
    """A minimal Stripe-shaped event the verifier can parse."""
    event = {
        "id": "evt_test_signature_check",
        "object": "event",
        "type": event_type,
        "api_version": "2024-12-18.acacia",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": "cs_test_xxx",
                "object": "checkout.session",
                "payment_status": "paid",
                "status": "complete",
                "metadata": {},
                "client_reference_id": None,
                "payment_intent": "pi_test_xxx",
            }
        },
    }
    return json.dumps(event, separators=(",", ":")).encode()


@pytest.fixture(autouse=True)
def _ensure_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the verifier at a deterministic test secret.

    We swap ``settings.stripe_webhook_secret`` and the Stripe SDK API
    key for the duration of each test so the verifier runs the same
    code path as in production while remaining independent of the
    developer's ``.env``.
    """
    test_secret = "whsec_unit_test_signature_secret_value"
    monkeypatch.setattr(settings, "stripe_webhook_secret", test_secret)
    # ``verify_webhook`` also calls ``_require_configured`` which
    # expects a (non-empty) Stripe secret key; we feed it a sandbox
    # placeholder so the function body progresses past the guard.
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_unit_only")
    return test_secret


@pytest.mark.unit
def test_valid_signature_returns_parsed_event(_ensure_secret: str) -> None:
    payload = _make_event_payload()
    header = _sign_payload(payload, _ensure_secret)

    event = verify_webhook(payload, header)

    assert event["id"] == "evt_test_signature_check"
    assert event["type"] == "checkout.session.completed"


@pytest.mark.unit
def test_tampered_payload_is_rejected(_ensure_secret: str) -> None:
    payload = _make_event_payload()
    header = _sign_payload(payload, _ensure_secret)

    # Tamper after signing — even a single byte change must invalidate
    # the signature.
    tampered = payload.replace(b'"payment_status":"paid"', b'"payment_status":"unpaid"')

    with pytest.raises(StripeServiceError) as exc:
        verify_webhook(tampered, header)
    assert "signature" in str(exc.value).lower()


@pytest.mark.unit
def test_wrong_secret_is_rejected(_ensure_secret: str) -> None:
    payload = _make_event_payload()
    header = _sign_payload(payload, "whsec_attacker_made_up_secret")

    with pytest.raises(StripeServiceError) as exc:
        verify_webhook(payload, header)
    assert "signature" in str(exc.value).lower()


@pytest.mark.unit
def test_missing_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty STRIPE_WEBHOOK_SECRET MUST refuse every request — never accept."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_unit_only")
    payload = _make_event_payload()

    with pytest.raises(StripeServiceError) as exc:
        verify_webhook(payload, "t=0,v1=anything")
    assert "not configured" in str(exc.value).lower()


@pytest.mark.unit
def test_malformed_payload_is_rejected(_ensure_secret: str) -> None:
    payload = b"{not real json"
    header = _sign_payload(payload, _ensure_secret)
    with pytest.raises(StripeServiceError):
        verify_webhook(payload, header)

"""Tests for the auto-refund decision logic.

The actual ``refund_payment_intent`` service hits real Stripe and
needs a live test-mode key, so we keep those checks for the manual
sandbox runs. Here we cover the decision rule that decides whether
an EUIPO failure should fire the refund at all — it is pure logic
keyed off the HTTP status code parsed out of the raw upstream error
string, so a small set of cases nails it down for good.
"""
from __future__ import annotations

import pytest

from app.payments.service import _should_auto_refund


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        # Permanent: the request itself is the problem, refunding the
        # customer immediately is the right call.
        ("Client error '400 Bad Request' for url 'https://x/y'", True),
        ("Client error '404 Not Found' for url 'https://x/y'", True),
        ("Client error '422 Unprocessable Entity' for url 'https://x/y'", True),
        ('{"status":400,"detail":"validation"}', True),
        ('{"status":422,"detail":"x"}', True),
        # Transient — auth / role / upstream outage. Money stays parked
        # so the operator can fix the integration and retry.
        ("Client error '401 Unauthorized' for url 'https://x/y'", False),
        ("Client error '403 Forbidden' for url 'https://x/y'", False),
        ("Client error '429 Too Many Requests' for url 'https://x/y'", False),
        ("Server error '500 Internal Server Error' for url 'https://x/y'", False),
        ("Server error '503 Service Unavailable' for url 'https://x/y'", False),
        ('{"status":401,"detail":"x"}', False),
        ('{"status":503,"detail":"x"}', False),
        # No status code visible at all → never auto-refund.
        ("", False),
        ("connection reset by peer", False),
        ("Network unreachable", False),
        # Auth-endpoint failures (token refresh) must NEVER trigger a
        # refund — they are operator-side issues, the customer's
        # filing has not been rejected. Even a 400 on the auth URL
        # stays parked.
        (
            "EUIPO refresh exchange returned 400: invalid_request. "
            "Cleared the persisted session — operator must re-run "
            "the OIDC bootstrap.",
            False,
        ),
        (
            "Client error '400 Bad Request' for url "
            "'https://auth-sandbox.euipo.europa.eu/cas-server-webapp/oidc/accessToken'",
            False,
        ),
        (
            "No EUIPO user session. Operator must re-run the OIDC bootstrap",
            False,
        ),
    ],
)
def test_auto_refund_decision(raw: str, expected: bool) -> None:
    assert _should_auto_refund(raw) is expected

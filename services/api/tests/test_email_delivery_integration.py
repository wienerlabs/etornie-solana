"""Real SMTP delivery integration test (#116).

Unlike ``test_email_transport.py`` (which mocks ``aiosmtplib.send``), this
test sends a message through a genuine SMTP connection to a live catcher
(Mailpit) and confirms it actually arrived by querying the catcher's HTTP
API — no mocks, real bytes over the wire.

It is skipped unless a Mailpit-style catcher is reachable and the app's
SMTP transport is configured, so it is a no-op where one has not been
provisioned. To run it locally:

    docker run -d -p 1025:1025 -p 8025:8025 axllent/mailpit
    # services/api/.env (or the environment):
    #   SMTP_HOST=localhost  SMTP_PORT=1025
    #   SMTP_STARTTLS=false   SMTP_USE_TLS=false
    #   SMTP_FROM_EMAIL=test@etornie.local
    .venv/bin/pytest tests/test_email_delivery_integration.py -v
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from app.notifications import email_transport
from app.notifications.email_transport import send_email

MAILPIT_API = os.environ.get("MAILPIT_API_URL", "http://localhost:8025")


def _mailpit_reachable() -> bool:
    try:
        return httpx.get(f"{MAILPIT_API}/api/v1/info", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_mailpit_reachable() and email_transport.is_configured()),
        reason="Mailpit catcher not reachable or SMTP transport not configured",
    ),
]


async def test_send_email_reaches_the_catcher() -> None:
    """A real send() lands in the catcher with the exact subject and body."""
    # A unique token so this assertion never collides with other messages
    # the catcher may already hold.
    token = uuid.uuid4().hex
    to_email = f"probe-{token}@etornie.test"
    subject = f"Etornie SMTP integration probe {token}"
    body = f"Delivery probe body {token}"

    sent = await send_email(
        to_email=to_email,
        to_name="Integration Probe",
        subject=subject,
        body=body,
    )
    assert sent is True

    # Find the message we just sent by its unique subject.
    search = httpx.get(
        f"{MAILPIT_API}/api/v1/search",
        params={"query": f"subject:\"{subject}\""},
        timeout=5.0,
    )
    assert search.status_code == 200
    messages = search.json().get("messages", [])
    assert len(messages) == 1, f"expected exactly one match, got {len(messages)}"

    delivered = messages[0]
    assert delivered["Subject"] == subject
    assert to_email in [addr["Address"] for addr in delivered["To"]]

    # Body is delivered intact (fetch the full message).
    full = httpx.get(
        f"{MAILPIT_API}/api/v1/message/{delivered['ID']}", timeout=5.0
    ).json()
    assert token in (full.get("Text") or full.get("HTML") or "")

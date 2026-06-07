"""Server-side SMTP transport — the single seam every email goes through.

Replaces the previous EmailJS REST usage (#29). EmailJS is a front-end-key
product: using its key server-side exposes it and gives no delivery
guarantees. This module ships transactional mail (registration OTP, case +
payment/filing/NFT notifications) over plain SMTP instead.

Provider-agnostic: point the ``SMTP_*`` settings at Amazon SES, Postmark,
Mailgun, Gmail, or any relay's SMTP endpoint. See
``docs/EMAIL_DELIVERABILITY.md`` for the SPF / DKIM / DMARC records a domain
needs before these messages reach the inbox.

Stays inert — logs and returns ``False``, never raises — when SMTP is not
configured, so local dev needs no email account and a flaky relay never
breaks a request path. Callers treat delivery as best-effort (the
registration flow additionally turns a ``False`` into a user-facing error).
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from email.utils import formataddr

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15.0


def is_configured() -> bool:
    """True when enough SMTP settings are present to attempt a send.

    A relay host and a From address are the minimum; username/password are
    optional because some relays (e.g. an in-VPC SES endpoint) authenticate
    by network identity rather than SMTP AUTH.
    """
    return bool(settings.smtp_host and settings.smtp_from_email)


def _build_message(
    *, to_email: str, to_name: str | None, subject: str, body: str
) -> EmailMessage:
    """Compose a plain-text message with properly encoded headers."""
    message = EmailMessage()
    message["From"] = formataddr(
        (settings.smtp_from_name or "Etornie", settings.smtp_from_email)
    )
    message["To"] = formataddr((to_name, to_email)) if to_name else to_email
    message["Subject"] = subject
    message.set_content(body)
    return message


async def send_email(
    *, to_email: str, to_name: str | None, subject: str, body: str
) -> bool:
    """Send one plain-text email. Returns ``True`` on success.

    Never raises: a missing configuration or a relay failure is logged and
    reported as ``False`` so callers can treat delivery as best-effort.
    """
    if not is_configured():
        logger.info("SMTP not configured; skipping email to %s", to_email)
        return False
    if not to_email:
        return False

    message = _build_message(
        to_email=to_email, to_name=to_name, subject=subject, body=body
    )

    # Port 465 wants implicit TLS; 587 wants STARTTLS. They are mutually
    # exclusive — never offer STARTTLS on top of an already-wrapped socket.
    use_tls = settings.smtp_use_tls
    start_tls = settings.smtp_starttls and not use_tls

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=_TIMEOUT_SECONDS,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        logger.warning("SMTP send to %s failed: %s", to_email, exc)
        return False

    logger.info("Email sent to %s (subject=%r)", to_email, subject)
    return True

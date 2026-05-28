"""Opt-in email notification dispatcher.

Single entry point the payment / filing / NFT hooks call after a
real event lands. Pulls the recipient address off the
:class:`app.users.models.User` row, honours the
``email_notifications_enabled`` toggle, and ships the message via the
already-configured EmailJS REST API (same provider the OTP flow
uses). Stays inert when EmailJS is not configured so local dev does
not require any external account.

Why this module
- One place that knows the opt-in rules → callers cannot
  accidentally send a notification to a user who did not consent.
- One place that knows about EmailJS payload shape → swapping the
  provider later (Resend, Postmark, SES) only touches this file.
- All sends are fire-and-forget (logged, never re-raised) so a flaky
  third-party never breaks the payment confirmation path.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.users.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationContent:
    """Render output: a subject + a body the email template substitutes in.

    EmailJS templates have a fixed set of variables they substitute
    (``to_name``, ``subject``, ``message`` …). Keep this dataclass
    minimal so any template the operator wires up just needs to know
    these three fields.
    """

    subject: str
    message: str


def _resolve_recipient(user: User) -> str | None:
    """Pick the recipient address per the opt-in rules.

    Returns ``None`` when the user has not opted in OR has not given
    us an address to send to. Callers MUST treat the returned None
    as "skip this notification" — never fall back to ``user.email``
    silently, because the login email is not an opt-in signal.
    """
    if not user.email_notifications_enabled:
        return None
    if user.notification_email:
        return user.notification_email
    # Some users sign up with an email AND set
    # email_notifications_enabled=True without touching the
    # notification_email field; treat the login email as the chosen
    # address in that case. Wallet-only users never end up here
    # because ``user.email`` is NULL for them.
    return user.email


async def _send_via_emailjs(
    *, to_email: str, to_name: str, content: NotificationContent
) -> bool:
    """Ship a single notification through the EmailJS REST API.

    Returns True on a 200 response, False otherwise. Never raises —
    the caller should treat email delivery as best-effort.
    """
    if not settings.emailjs_service_id or not settings.emailjs_public_key:
        logger.info("EmailJS not configured; skipping notification to %s", to_email)
        return False

    template_id = settings.emailjs_case_template_id or settings.emailjs_template_id
    if not template_id:
        logger.info("No EmailJS template_id configured; skipping notification")
        return False

    payload: dict[str, Any] = {
        "service_id": settings.emailjs_service_id,
        "template_id": template_id,
        "user_id": settings.emailjs_public_key,
        "accessToken": settings.emailjs_private_key,
        "template_params": {
            "to_name": to_name,
            "email": to_email,
            "subject": content.subject,
            "message": content.message,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.emailjs.com/api/v1.0/email/send", json=payload
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "EmailJS request failed for %s: %s", to_email, exc
        )
        return False
    if response.status_code != 200:
        logger.warning(
            "EmailJS returned %s for %s: %s",
            response.status_code,
            to_email,
            response.text[:200],
        )
        return False
    return True


async def send_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: NotificationContent,
) -> bool:
    """Send a notification to ``user_id`` if they have opted in.

    Returns True when an email was dispatched, False otherwise
    (no opt-in, no recipient, EmailJS not configured, delivery
    failure). Never raises — callers can treat this purely as a
    fire-and-forget side effect.
    """
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        logger.warning("send_notification: user %s not found", user_id)
        return False
    recipient = _resolve_recipient(user)
    if recipient is None:
        logger.debug(
            "send_notification: user %s opted out / no address; skipping",
            user_id,
        )
        return False
    return await _send_via_emailjs(
        to_email=recipient,
        to_name=user.full_name or "Etornie user",
        content=content,
    )


def schedule_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: NotificationContent,
) -> None:
    """Fire-and-forget convenience: spawn the send as a background task.

    The Stripe webhook handler should not block on an email delivery,
    so callers that do not need the return value just call this. The
    asyncio task lives on the event loop the request is running in;
    failures are logged inside ``_send_via_emailjs``.
    """
    asyncio.get_event_loop().create_task(
        send_notification(db, user_id=user_id, content=content)
    )


# ---------------------------------------------------------------------------
# Content templates — keep wording in one spot so we can iterate on
# tone without grepping the codebase. Callers pass the structured
# context and get back a ready-to-send ``NotificationContent``.
# ---------------------------------------------------------------------------


def payment_received_content(
    *,
    amount_label: str,
    platform: str,
    case_number: str | None,
    stripe_receipt_url: str | None,
    compliance_tx_url: str | None,
) -> NotificationContent:
    lines: list[str] = [
        f"Your payment of {amount_label} for the {platform} filing has been received.",
        "",
    ]
    if case_number:
        lines.append(f"Case reference: {case_number}")
    if stripe_receipt_url:
        lines.append(f"Stripe receipt: {stripe_receipt_url}")
    if compliance_tx_url:
        lines.append(f"On-chain compliance proof: {compliance_tx_url}")
    lines += [
        "",
        "The filing is now in the submission queue. You'll get another "
        "email once it lands at the IP office.",
        "",
        "— Etornie",
    ]
    return NotificationContent(
        subject=f"Payment received — {platform} filing",
        message="\n".join(lines),
    )


def refund_issued_content(
    *,
    amount_label: str,
    reason: str,
    stripe_refund_id: str,
) -> NotificationContent:
    message = (
        f"Your payment of {amount_label} has been refunded to the original "
        "card. The card-issuing bank usually shows it within 5-10 "
        "business days.\n\n"
        f"Reason: {reason}\n"
        f"Stripe refund id: {stripe_refund_id}\n\n"
        "No further action required.\n\n"
        "— Etornie"
    )
    return NotificationContent(
        subject=f"Refund issued — {amount_label}",
        message=message,
    )


def filing_submitted_content(
    *,
    platform: str,
    external_reference: str,
    case_number: str | None,
) -> NotificationContent:
    message = (
        f"Your {platform} application has been submitted to the IP office.\n\n"
        f"Application number: {external_reference}\n"
    )
    if case_number:
        message += f"Case reference: {case_number}\n"
    message += (
        "\nYou can claim the soul-bound NFT certifying this filing from "
        "your dashboard whenever you connect a Solana wallet.\n\n"
        "— Etornie"
    )
    return NotificationContent(
        subject=f"Filing submitted — {platform} {external_reference}",
        message=message,
    )


def nft_ready_content(*, case_number: str) -> NotificationContent:
    message = (
        f"The Token-2022 NFT for case {case_number} is set up on Solana "
        "and ready to be claimed.\n\n"
        "Connect your wallet from the dashboard and sign the claim "
        "transaction to move it into your account.\n\n"
        "— Etornie"
    )
    return NotificationContent(
        subject=f"NFT ready to claim — case {case_number}",
        message=message,
    )

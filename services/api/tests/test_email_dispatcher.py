"""Tests for the opt-in email dispatcher logic.

Pure unit tests — the actual ``_send_via_emailjs`` call hits a real
provider, so we exercise the decision rules around it without
firing a network request. The rules that matter most:

- A user who has NOT opted in MUST never receive a notification,
  even if they have a login email on file. The login email is not
  a consent signal.
- A user who HAS opted in but supplied no address still gets None
  (no silent fallback to a non-opt-in field).
- The opt-in path returns the dedicated address when set, otherwise
  the login email as a sensible last resort.
"""
from __future__ import annotations

import uuid

import pytest

from app.notifications.email_dispatcher import (
    NotificationContent,
    _resolve_recipient,
    filing_submitted_content,
    nft_ready_content,
    payment_received_content,
    refund_issued_content,
)
from app.users.models import AuthMethod, User, UserRole


def _make_user(
    *,
    login_email: str | None,
    notification_email: str | None,
    opted_in: bool,
) -> User:
    return User(
        id=uuid.uuid4(),
        email=login_email,
        hashed_password="x" * 60 if login_email else None,
        full_name="Test User",
        role=UserRole.client,
        auth_method=(
            AuthMethod.email.value if login_email else AuthMethod.wallet.value
        ),
        notification_email=notification_email,
        email_notifications_enabled=opted_in,
    )


@pytest.mark.unit
class TestRecipientResolution:
    def test_opted_out_user_never_resolves(self) -> None:
        user = _make_user(
            login_email="login@example.com",
            notification_email="notify@example.com",
            opted_in=False,
        )
        assert _resolve_recipient(user) is None

    def test_opted_in_prefers_dedicated_notification_email(self) -> None:
        user = _make_user(
            login_email="login@example.com",
            notification_email="notify@example.com",
            opted_in=True,
        )
        assert _resolve_recipient(user) == "notify@example.com"

    def test_opted_in_falls_back_to_login_email_when_dedicated_missing(self) -> None:
        user = _make_user(
            login_email="login@example.com",
            notification_email=None,
            opted_in=True,
        )
        assert _resolve_recipient(user) == "login@example.com"

    def test_opted_in_wallet_user_with_no_address_returns_none(self) -> None:
        # Wallet-only signup: no login email, hasn't supplied
        # notification_email yet. Toggling opt-in alone doesn't
        # magic up an address — return None so the dispatcher skips
        # silently.
        user = _make_user(
            login_email=None,
            notification_email=None,
            opted_in=True,
        )
        assert _resolve_recipient(user) is None

    def test_wallet_user_with_dedicated_email_only(self) -> None:
        user = _make_user(
            login_email=None,
            notification_email="notify@example.com",
            opted_in=True,
        )
        assert _resolve_recipient(user) == "notify@example.com"


@pytest.mark.unit
class TestContentTemplates:
    """Templates are pure formatting — verify the user-relevant data
    lands in subject + body and nothing technical bleeds through."""

    def test_payment_received_includes_amount_and_links(self) -> None:
        content = payment_received_content(
            amount_label="€900.00",
            platform="EUIPO",
            case_number="ETR-2026-0042",
            stripe_receipt_url="https://pay.stripe.com/receipts/x",
            compliance_tx_url="https://explorer.solana.com/tx/y",
        )
        assert isinstance(content, NotificationContent)
        assert "€900.00" in content.message
        assert "EUIPO" in content.subject
        assert "ETR-2026-0042" in content.message
        assert "https://pay.stripe.com/receipts/x" in content.message
        assert "https://explorer.solana.com/tx/y" in content.message

    def test_payment_received_optional_fields_omitted_cleanly(self) -> None:
        content = payment_received_content(
            amount_label="£265.00",
            platform="UK IPO",
            case_number=None,
            stripe_receipt_url=None,
            compliance_tx_url=None,
        )
        assert "£265.00" in content.message
        # No "None" / "null" strings leak.
        assert "None" not in content.message
        assert "null" not in content.message.lower()

    def test_refund_issued_includes_reason_and_refund_id(self) -> None:
        content = refund_issued_content(
            amount_label="€900.00",
            reason="EUIPO rejected the submission permanently",
            stripe_refund_id="re_test_123",
        )
        assert "€900.00" in content.subject
        assert "EUIPO rejected the submission permanently" in content.message
        assert "re_test_123" in content.message

    def test_filing_submitted_includes_app_number(self) -> None:
        content = filing_submitted_content(
            platform="EUIPO",
            external_reference="EUTM-018000000",
            case_number="ETR-2026-0099",
        )
        assert "EUIPO" in content.subject
        assert "EUTM-018000000" in content.subject
        assert "ETR-2026-0099" in content.message

    def test_nft_ready_includes_case_number(self) -> None:
        content = nft_ready_content(case_number="ETR-2026-0099")
        assert "ETR-2026-0099" in content.subject
        assert "ETR-2026-0099" in content.message

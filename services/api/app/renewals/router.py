"""Renewal API surface.

Two routes today:
- POST /cases/{case_id}/renew/checkout: create a Stripe Checkout
  session for the renewal fee, return the URL the frontend should
  redirect the user to.
- GET  /cases/{case_id}/renewal-status: structured renewal lifecycle
  snapshot (due date, days remaining, current window, reminder
  history) so the case detail page can paint a single accurate
  badge.

The renewal flow re-uses the existing PaymentIntent table by
attaching the renewal intent to the same CaseDraft that originally
produced the case (the draft row stays alive after promotion). A
distinct ``intent_kind="renewal"`` metadata flag + per-cycle
idempotency key prevents collision with the initial filing intent.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import (
    CaseDraft,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentProvider,
    PaymentType,
)
from app.auth.dependencies import get_current_user
from app.cases.models import Case
from app.config import settings
from app.database import get_db
from app.errors import translate_stripe_error
from app.renewals.models import RenewalReminder
from app.renewals.service import REMINDER_WINDOWS_DAYS, detect_open_window
from app.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", tags=["renewals"])

# Fee schedule lives at ``services/api/data/euipo_fees.json``.
# parents[0]=renewals/, parents[1]=app/, parents[2]=services/api/.
_FEES_PATH = Path(__file__).resolve().parents[2] / "data" / "euipo_fees.json"


def _load_renewal_schedule() -> dict[str, Any]:
    if not _FEES_PATH.is_file():
        raise RuntimeError(
            f"EUIPO fee schedule not found at {_FEES_PATH}; renewals "
            "cannot be priced."
        )
    data = json.loads(_FEES_PATH.read_text())
    return data["trademark"]["renewal"], data.get("currency", "EUR")


def _compute_renewal_fee(nice_classes_csv: str | None) -> tuple[int, str]:
    """Return (total_eur, currency) for the renewal fee.

    Mirrors the initial-application fee schedule from data/euipo_fees.json
    (renewal schedule is the same shape: first_class + second_class +
    additional_class_each * extras).
    """
    schedule, currency = _load_renewal_schedule()
    classes: list[int] = []
    for part in (nice_classes_csv or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            classes.append(int(part))
        except ValueError:
            continue
    if not classes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Case has no Nice classes; renewal cannot be priced.",
        )
    total = schedule["first_class"]
    if len(classes) >= 2:
        total += schedule["second_class"]
    if len(classes) >= 3:
        total += schedule["additional_class_each"] * (len(classes) - 2)
    return total, currency


async def _resolve_source_draft(db: AsyncSession, case: Case) -> CaseDraft:
    """Find the CaseDraft that produced this case.

    Every promoted draft stamps ``promoted_case_id`` so the reverse
    lookup is unambiguous. Raises 409 if no such draft is found —
    means the case predates the agent flow.
    """
    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.promoted_case_id == case.id)
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This case was not created via the agent flow; renewal is "
            "not yet wired for it.",
        )
    return draft


def _current_renewal_cycle(case: Case) -> int:
    """0-based renewal cycle counter.

    Each successful renewal stamps ``last_renewed_at``. We do not
    persist a counter column today; the cycle is implied by how many
    times renewal_due_at has advanced beyond filing_date+10y. For
    idempotency keys we just compute it from the difference, falling
    back to 0 when filing_date is missing.
    """
    if case.filing_date is None or case.renewal_due_at is None:
        return 0
    from app.renewals.service import EUIPO_RENEWAL_TERM_YEARS

    delta_years = case.renewal_due_at.year - case.filing_date.year
    return max(0, delta_years // EUIPO_RENEWAL_TERM_YEARS - 1)


class RenewalCheckoutResponse(BaseModel):
    payment_intent_id: uuid.UUID
    checkout_url: str
    amount: Decimal
    currency: str
    expires_at: datetime | None


@router.post(
    "/{case_id}/renew/checkout",
    response_model=RenewalCheckoutResponse,
)
async def create_renewal_checkout(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RenewalCheckoutResponse:
    """Create a Stripe Checkout session for the renewal fee."""
    if not settings.stripe_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stripe is not configured on this environment.",
        )
    stripe.api_key = settings.stripe_secret_key

    case = (
        await db.execute(select(Case).where(Case.id == case_id))
    ).scalar_one_or_none()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    # Owner OR admin may trigger the renewal flow. The admin path is
    # the "manual operator nudge" — same Stripe Checkout, same
    # webhook handling — kept open so support can complete a
    # renewal on behalf of a stuck user.
    if case.client_id != user.id and user.role.value != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only renew your own cases.",
        )
    if case.renewal_due_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This case has no renewal due date yet; renewal is not "
            "applicable.",
        )

    draft = await _resolve_source_draft(db, case)

    amount, currency = _compute_renewal_fee(case.nice_classes)
    cycle = _current_renewal_cycle(case)
    idempotency_key = (
        f"draft:{draft.id}:renewal:EUIPO:cycle:{cycle}"
    )

    # Reuse an in-flight intent (same idempotency key) so a duplicate
    # click does not double-charge — Stripe will return the same
    # Checkout session because we pass the same idempotency key
    # below.
    intent = (
        await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if intent is None:
        intent = PaymentIntent(
            case_draft_id=draft.id,
            payment_type=PaymentType.platform_fee,
            provider=PaymentProvider.stripe,
            amount=Decimal(amount),
            currency=currency,
            status=PaymentIntentStatus.created,
            idempotency_key=idempotency_key,
            gateway_metadata={
                "intent_kind": "renewal",
                "renewal_case_id": str(case.id),
                "renewal_cycle": cycle,
                "platform": "EUIPO",
            },
        )
        db.add(intent)
        await db.flush()

    success_url = settings.stripe_success_url
    cancel_url = settings.stripe_cancel_url

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": amount * 100,
                        "product_data": {
                            "name": (
                                f"EUIPO renewal — {case.case_number}"
                            ),
                            "description": (
                                f"10-year renewal of trademark "
                                f"{case.title or case.case_number} for "
                                f"Nice classes {case.nice_classes or '-'}"
                            ),
                        },
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(intent.id),
            customer_email=user.email,
            metadata={
                "payment_intent_id": str(intent.id),
                "case_draft_id": str(draft.id),
                "case_id": str(case.id),
                "intent_kind": "renewal",
                "renewal_cycle": str(cycle),
                "platform": "EUIPO",
            },
            payment_intent_data={
                "metadata": {
                    "payment_intent_id": str(intent.id),
                    "case_id": str(case.id),
                    "intent_kind": "renewal",
                }
            },
            idempotency_key=idempotency_key,
        )
    except stripe.StripeError as exc:
        translated = translate_stripe_error(exc)
        raise HTTPException(
            translated.http_status, translated.user_message
        ) from exc

    metadata = dict(intent.gateway_metadata or {})
    metadata["stripe_session_id"] = session.id
    metadata["checkout_url"] = session.url
    intent.gateway_metadata = metadata
    intent.gateway_payment_id = session.payment_intent or session.id
    intent.status = PaymentIntentStatus.awaiting
    await db.commit()
    await db.refresh(intent)

    return RenewalCheckoutResponse(
        payment_intent_id=intent.id,
        checkout_url=session.url,
        amount=intent.amount,
        currency=intent.currency,
        expires_at=(
            datetime.fromtimestamp(session.expires_at, tz=timezone.utc)
            if session.expires_at
            else None
        ),
    )


class RenewalReminderRow(BaseModel):
    window_days: int
    target_due_at: datetime
    sent_at: datetime
    channels: list[str]


class RenewalStatusResponse(BaseModel):
    case_id: uuid.UUID
    renewal_due_at: datetime | None
    last_renewed_at: datetime | None
    days_remaining: int | None
    open_window_days: int | None
    is_overdue: bool
    reminders: list[RenewalReminderRow]


@router.get(
    "/{case_id}/renewal-status",
    response_model=RenewalStatusResponse,
)
async def renewal_status(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RenewalStatusResponse:
    case = (
        await db.execute(select(Case).where(Case.id == case_id))
    ).scalar_one_or_none()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if case.client_id != user.id and user.role.value != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    now = datetime.now(tz=timezone.utc)
    days_remaining: int | None = None
    open_window: int | None = None
    is_overdue = False
    if case.renewal_due_at is not None:
        due = case.renewal_due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        days_remaining = (due.date() - now.date()).days
        is_overdue = due <= now
        open_window = detect_open_window(
            renewal_due_at=due, now=now, windows=REMINDER_WINDOWS_DAYS
        )

    rows = (
        await db.execute(
            select(RenewalReminder)
            .where(RenewalReminder.case_id == case_id)
            .order_by(RenewalReminder.sent_at.desc())
        )
    ).scalars().all()
    reminder_rows = [
        RenewalReminderRow(
            window_days=r.window_days,
            target_due_at=r.target_due_at,
            sent_at=r.sent_at,
            channels=list(r.channels or []),
        )
        for r in rows
    ]

    return RenewalStatusResponse(
        case_id=case.id,
        renewal_due_at=case.renewal_due_at,
        last_renewed_at=case.last_renewed_at,
        days_remaining=days_remaining,
        open_window_days=open_window,
        is_overdue=is_overdue,
        reminders=reminder_rows,
    )

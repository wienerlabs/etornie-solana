"""Admin operator panel — observability + actions.

Every endpoint here requires ``UserRole.admin``. Routes return trimmed
DTOs and (deliberately) bound page_size at 200 so a curious admin
cannot accidentally page through millions of rows from the browser.

The panel intentionally re-uses existing service-layer helpers:
``refund_payment_intent`` for refunds, ``submit_eutm`` for filing
retries, so the audit / Sentry hooks already attached to those code
paths fire from the admin lane too.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import (
    AdminAnalyticsSummary,
    AdminAnalyticsTimeline,
    AdminCaseRow,
    AdminFilingRow,
    AdminListResponse,
    AdminOverviewCounts,
    AdminPaymentRow,
    AdminRetryFilingResponse,
    AdminTimelineEvent,
    AdminUpcomingRenewal,
)
from app.renewals.models import RenewalReminder
from app.renewals.service import (
    ReminderDispatchResult,
    scan_and_dispatch_due_reminders,
)
from app.security.models import OperatorKeyAccessLog
from app.agent.models import AgentSession
from app.cost.pricing import compute_cost_usd, rate_for_model
from app.agent.filing_service import FilingServiceError, submit_eutm
from app.agent.models import (
    CaseDraft,
    FilingAttempt,
    FilingAttemptStatus,
    PaymentIntent,
    PaymentIntentStatus,
)
from app.auth.dependencies import require_role
from app.cases.models import Case, CaseNftState, CaseStatus
from app.database import get_db
from app.payments import service as stripe_service
from app.payments.schemas import RefundPaymentIntentRequest
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(UserRole.admin))],
)

_MAX_PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


async def _count_by_enum(
    db: AsyncSession, column
) -> dict[str, int]:
    """COUNT(*) GROUP BY for an enum column. Empty result = empty dict."""
    rows = (
        await db.execute(
            select(column, func.count()).group_by(column)
        )
    ).all()
    out: dict[str, int] = {}
    for value, count in rows:
        if value is None:
            key = "unknown"
        elif hasattr(value, "value"):
            key = value.value
        else:
            key = str(value)
        out[key] = int(count)
    return out


@router.get("/overview", response_model=AdminOverviewCounts)
async def overview(
    db: AsyncSession = Depends(get_db),
) -> AdminOverviewCounts:
    """Operator dashboard snapshot — counts by status + confirmed totals."""
    users_total = int(
        (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    )
    users_active = int(
        (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.is_active.is_(True))
            )
        ).scalar()
        or 0
    )

    cases_total = int(
        (await db.execute(select(func.count()).select_from(Case))).scalar() or 0
    )
    cases_by_status = await _count_by_enum(db, Case.status)

    payments_total = int(
        (
            await db.execute(select(func.count()).select_from(PaymentIntent))
        ).scalar()
        or 0
    )
    payments_by_status = await _count_by_enum(db, PaymentIntent.status)

    # SUM(amount) per currency for confirmed intents — the operator
    # cards show total revenue grouped by currency (EUR + GBP today)
    # so cross-currency aggregation does not produce nonsense.
    confirmed_amount_rows = (
        await db.execute(
            select(
                PaymentIntent.currency,
                func.sum(PaymentIntent.amount),
            )
            .where(PaymentIntent.status == PaymentIntentStatus.confirmed)
            .group_by(PaymentIntent.currency)
        )
    ).all()
    payments_confirmed_amount: dict[str, Decimal] = {}
    for currency, total in confirmed_amount_rows:
        if currency is None:
            continue
        payments_confirmed_amount[str(currency).upper()] = Decimal(total or 0)

    filings_total = int(
        (
            await db.execute(select(func.count()).select_from(FilingAttempt))
        ).scalar()
        or 0
    )
    filings_by_status = await _count_by_enum(db, FilingAttempt.status)

    nft_states = await _count_by_enum(db, Case.nft_state)

    return AdminOverviewCounts(
        users_total=users_total,
        users_active=users_active,
        cases_total=cases_total,
        cases_by_status=cases_by_status,
        payments_total=payments_total,
        payments_by_status=payments_by_status,
        payments_confirmed_amount=payments_confirmed_amount,
        filings_total=filings_total,
        filings_by_status=filings_by_status,
        nft_states=nft_states,
    )


# ---------------------------------------------------------------------------
# Payments list + admin actions
# ---------------------------------------------------------------------------


def _payment_meta_get(intent: PaymentIntent, key: str) -> Any:
    meta = intent.gateway_metadata or {}
    return meta.get(key)


def _payment_to_row(
    intent: PaymentIntent,
    *,
    draft: CaseDraft | None,
    user: User | None,
    case: Case | None,
) -> AdminPaymentRow:
    return AdminPaymentRow(
        id=intent.id,
        case_draft_id=intent.case_draft_id,
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        user_full_name=user.full_name if user else None,
        provider=intent.provider.value,
        payment_type=intent.payment_type.value,
        status=intent.status.value,
        amount=intent.amount,
        currency=intent.currency,
        gateway_payment_id=intent.gateway_payment_id,
        idempotency_key=intent.idempotency_key,
        refund_id=_payment_meta_get(intent, "refund_id"),
        refund_amount=(
            Decimal(_payment_meta_get(intent, "refund_amount"))
            if _payment_meta_get(intent, "refund_amount") is not None
            else None
        ),
        refund_status=_payment_meta_get(intent, "refund_status"),
        filing_external_reference=_payment_meta_get(
            intent, "filing_external_reference"
        ),
        filing_status=_payment_meta_get(intent, "filing_status"),
        filing_error=_payment_meta_get(intent, "filing_error"),
        case_id=case.id if case else None,
        case_number=case.case_number if case else None,
        compliance_onchain_tx=_payment_meta_get(intent, "compliance_onchain_tx"),
        auto_submit_committed_at=_payment_meta_get(
            intent, "auto_submit_committed_at"
        ),
        created_at=intent.created_at,
        confirmed_at=intent.confirmed_at,
    )


@router.get("/payments", response_model=AdminListResponse)
async def list_payments(
    db: AsyncSession = Depends(get_db),
    payment_status: str | None = Query(None, alias="status"),
    provider: str | None = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> AdminListResponse:
    """Paginated payment intents with embedded user/draft/case context."""
    stmt = select(PaymentIntent)
    if payment_status:
        try:
            stmt = stmt.where(
                PaymentIntent.status == PaymentIntentStatus(payment_status)
            )
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown payment status: {payment_status}",
            )
    if provider:
        stmt = stmt.where(PaymentIntent.provider == provider)

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar()
        or 0
    )

    stmt = (
        stmt.order_by(PaymentIntent.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    intents = (await db.execute(stmt)).scalars().all()

    # Batch-load drafts + users + cases so we never N+1 the page.
    draft_ids = {i.case_draft_id for i in intents if i.case_draft_id}
    drafts: dict[uuid.UUID, CaseDraft] = {}
    if draft_ids:
        drafts = {
            d.id: d
            for d in (
                await db.execute(
                    select(CaseDraft).where(CaseDraft.id.in_(draft_ids))
                )
            ).scalars()
        }
    user_ids = {d.user_id for d in drafts.values() if d.user_id}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        users = {
            u.id: u
            for u in (
                await db.execute(select(User).where(User.id.in_(user_ids)))
            ).scalars()
        }
    case_ids = {d.promoted_case_id for d in drafts.values() if d.promoted_case_id}
    cases: dict[uuid.UUID, Case] = {}
    if case_ids:
        cases = {
            c.id: c
            for c in (
                await db.execute(select(Case).where(Case.id.in_(case_ids)))
            ).scalars()
        }

    items: list[dict[str, Any]] = []
    for intent in intents:
        draft = drafts.get(intent.case_draft_id) if intent.case_draft_id else None
        user = users.get(draft.user_id) if draft and draft.user_id else None
        case = (
            cases.get(draft.promoted_case_id)
            if draft and draft.promoted_case_id
            else None
        )
        items.append(
            _payment_to_row(intent, draft=draft, user=user, case=case).model_dump(
                mode="json"
            )
        )

    return AdminListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.post(
    "/payments/{intent_id}/refund",
    response_model=AdminPaymentRow,
)
async def refund_payment(
    intent_id: uuid.UUID,
    body: RefundPaymentIntentRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.admin)),
) -> AdminPaymentRow:
    """Issue a Stripe refund for an admin-selected payment intent.

    Re-uses the service-layer ``refund_payment_intent`` so the same
    auto-refund hooks (chat confirmation, EmailJS notify, audit log)
    fire whether the trigger is the auto-pipeline or this endpoint.
    """
    intent = (
        await db.execute(
            select(PaymentIntent).where(PaymentIntent.id == intent_id)
        )
    ).scalar_one_or_none()
    if intent is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Payment intent {intent_id} not found"
        )
    try:
        refunded = await stripe_service.refund_payment_intent(
            db,
            intent,
            reason=body.reason,
            initiated_by=f"admin:{actor.id}",
        )
    except stripe_service.StripeServiceError as exc:
        raise HTTPException(
            exc.http_status,
            exc.user_message,
        ) from exc

    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == refunded.case_draft_id)
        )
    ).scalar_one_or_none() if refunded.case_draft_id else None
    user = (
        await db.execute(select(User).where(User.id == draft.user_id))
    ).scalar_one_or_none() if draft and draft.user_id else None
    case = (
        await db.execute(
            select(Case).where(Case.id == draft.promoted_case_id)
        )
    ).scalar_one_or_none() if draft and draft.promoted_case_id else None
    return _payment_to_row(refunded, draft=draft, user=user, case=case)


# ---------------------------------------------------------------------------
# Filing attempts + retry
# ---------------------------------------------------------------------------


def _filing_to_row(
    attempt: FilingAttempt,
    *,
    draft: CaseDraft | None,
    user: User | None,
) -> AdminFilingRow:
    return AdminFilingRow(
        id=attempt.id,
        case_draft_id=attempt.case_draft_id,
        platform=attempt.platform.value,
        status=attempt.status.value,
        attempt_number=attempt.attempt_number,
        external_reference=attempt.external_reference,
        error_message=attempt.error_message,
        submitted_at=attempt.submitted_at,
        completed_at=attempt.completed_at,
        created_at=attempt.created_at,
        updated_at=attempt.updated_at,
        case_draft_mark_text=draft.mark_text if draft else None,
        case_draft_user_id=draft.user_id if draft else None,
        case_draft_user_email=user.email if user else None,
    )


@router.get("/filings", response_model=AdminListResponse)
async def list_filings(
    db: AsyncSession = Depends(get_db),
    filing_status: str | None = Query(None, alias="status"),
    platform: str | None = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> AdminListResponse:
    stmt = select(FilingAttempt)
    if filing_status:
        try:
            stmt = stmt.where(
                FilingAttempt.status == FilingAttemptStatus(filing_status)
            )
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown filing status: {filing_status}",
            )
    if platform:
        stmt = stmt.where(FilingAttempt.platform == platform)

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar()
        or 0
    )

    stmt = (
        stmt.order_by(FilingAttempt.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    attempts = (await db.execute(stmt)).scalars().all()

    draft_ids = {a.case_draft_id for a in attempts}
    drafts: dict[uuid.UUID, CaseDraft] = {}
    if draft_ids:
        drafts = {
            d.id: d
            for d in (
                await db.execute(
                    select(CaseDraft).where(CaseDraft.id.in_(draft_ids))
                )
            ).scalars()
        }
    user_ids = {d.user_id for d in drafts.values() if d.user_id}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        users = {
            u.id: u
            for u in (
                await db.execute(select(User).where(User.id.in_(user_ids)))
            ).scalars()
        }

    items: list[dict[str, Any]] = []
    for attempt in attempts:
        draft = drafts.get(attempt.case_draft_id)
        user = users.get(draft.user_id) if draft and draft.user_id else None
        items.append(
            _filing_to_row(attempt, draft=draft, user=user).model_dump(mode="json")
        )

    return AdminListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.post(
    "/filings/{attempt_id}/retry",
    response_model=AdminRetryFilingResponse,
)
async def retry_filing(
    attempt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.admin)),
) -> AdminRetryFilingResponse:
    """Re-attempt a filing whose previous attempt errored or was rejected.

    Loads the original FilingAttempt's CaseDraft and re-calls
    ``submit_eutm`` with ``initiated_by="admin_retry:<actor>"`` so the
    new attempt row gets a clean audit trail. The endpoint is
    intentionally a no-op when the draft already has a submitted
    attempt — we never want to double-file with EUIPO.
    """
    attempt = (
        await db.execute(
            select(FilingAttempt).where(FilingAttempt.id == attempt_id)
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Filing attempt {attempt_id} not found"
        )
    if attempt.platform.value != "EUIPO":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Retry is only wired for EUIPO; got {attempt.platform.value}.",
        )
    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == attempt.case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Underlying draft {attempt.case_draft_id} not found.",
        )

    try:
        outcome = await submit_eutm(
            db, draft, initiated_by=f"admin_retry:{actor.id}"
        )
    except FilingServiceError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, str(exc)
        ) from exc
    await db.commit()

    return AdminRetryFilingResponse(
        filing_attempt_id=uuid.UUID(outcome["filing_attempt_id"]),
        status=outcome["status"],
        external_reference=outcome.get("external_reference"),
        error=outcome.get("error"),
    )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _case_to_row(case: Case, *, client: User | None) -> AdminCaseRow:
    return AdminCaseRow(
        id=case.id,
        case_number=case.case_number,
        title=case.title,
        case_type=case.case_type.value,
        jurisdiction=case.jurisdiction,
        status=case.status.value,
        client_id=case.client_id,
        client_email=client.email if client else None,
        client_wallet=case.client_wallet,
        nft_state=case.nft_state.value if case.nft_state else None,
        nft_mint=case.nft_mint,
        attestation_tx=case.attestation_tx,
        filing_date=case.filing_date,
        deadline=case.deadline,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@router.get("/cases", response_model=AdminListResponse)
async def list_cases(
    db: AsyncSession = Depends(get_db),
    case_status: str | None = Query(None, alias="status"),
    nft_state: str | None = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> AdminListResponse:
    stmt = select(Case)
    if case_status:
        try:
            stmt = stmt.where(Case.status == CaseStatus(case_status))
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown case status: {case_status}",
            )
    if nft_state:
        try:
            stmt = stmt.where(Case.nft_state == CaseNftState(nft_state))
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown nft_state: {nft_state}",
            )

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar()
        or 0
    )

    stmt = (
        stmt.order_by(Case.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    cases = (await db.execute(stmt)).scalars().all()

    client_ids = {c.client_id for c in cases if c.client_id}
    clients: dict[uuid.UUID, User] = {}
    if client_ids:
        clients = {
            u.id: u
            for u in (
                await db.execute(select(User).where(User.id.in_(client_ids)))
            ).scalars()
        }

    items: list[dict[str, Any]] = []
    for case in cases:
        client = clients.get(case.client_id) if case.client_id else None
        items.append(_case_to_row(case, client=client).model_dump(mode="json"))

    return AdminListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


# ---------------------------------------------------------------------------
# Renewal dispatcher trigger
# ---------------------------------------------------------------------------


@router.post("/renewals/dispatch")
async def dispatch_renewal_reminders(
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Run the renewal reminder scan once and return the counts.

    Endpoint exists so an external scheduler (k8s CronJob, GitHub
    Actions, etc.) can pulse the dispatcher without needing direct
    DB access. Idempotent against concurrent runs because the
    underlying dispatcher relies on the unique constraint on
    ``renewal_reminder`` to deduplicate (window, target_due_at).
    """
    result: ReminderDispatchResult = await scan_and_dispatch_due_reminders(db)
    await db.commit()
    return {
        "scanned": result.scanned,
        "dispatched": result.dispatched,
        "skipped_due_to_existing": result.skipped_due_to_existing,
    }


# ---------------------------------------------------------------------------
# Analytics (system-wide)
# ---------------------------------------------------------------------------


# Filing statuses that count as "successful" for the success-rate
# denominator. ``submitted`` is the canonical happy path; ``accepted``
# is the rarer terminal state.
_SUCCESSFUL_FILING_STATUSES = {
    FilingAttemptStatus.submitted,
    FilingAttemptStatus.accepted,
}
_FAILED_FILING_STATUSES = {
    FilingAttemptStatus.rejected,
    FilingAttemptStatus.error,
}


@router.get("/analytics/summary", response_model=AdminAnalyticsSummary)
async def analytics_summary(
    db: AsyncSession = Depends(get_db),
) -> AdminAnalyticsSummary:
    """System-wide analytics snapshot for the operator panel."""
    # cases
    case_rows = (
        await db.execute(
            select(Case.status, func.count()).group_by(Case.status)
        )
    ).all()
    cases_total = 0
    cases_open = 0
    cases_closed = 0
    for status_value, count in case_rows:
        n = int(count)
        cases_total += n
        if status_value == CaseStatus.closed:
            cases_closed += n
        else:
            cases_open += n

    # filings
    filing_rows = (
        await db.execute(
            select(FilingAttempt.status, func.count()).group_by(
                FilingAttempt.status
            )
        )
    ).all()
    filings_total = 0
    filings_successful = 0
    filings_failed = 0
    for status_value, count in filing_rows:
        n = int(count)
        filings_total += n
        if status_value in _SUCCESSFUL_FILING_STATUSES:
            filings_successful += n
        elif status_value in _FAILED_FILING_STATUSES:
            filings_failed += n
    completed = filings_successful + filings_failed
    success_rate: float | None = (
        round(filings_successful / completed, 4) if completed > 0 else None
    )

    # money by currency
    revenue_rows = (
        await db.execute(
            select(PaymentIntent.currency, func.sum(PaymentIntent.amount))
            .where(PaymentIntent.status == PaymentIntentStatus.confirmed)
            .group_by(PaymentIntent.currency)
        )
    ).all()
    total_revenue: dict[str, Decimal] = {}
    for currency, total in revenue_rows:
        if currency is None:
            continue
        total_revenue[str(currency).upper()] = Decimal(total or 0)

    refunded_rows = (
        await db.execute(
            select(PaymentIntent.currency, func.sum(PaymentIntent.amount))
            .where(PaymentIntent.status == PaymentIntentStatus.refunded)
            .group_by(PaymentIntent.currency)
        )
    ).all()
    total_refunded: dict[str, Decimal] = {}
    for currency, total in refunded_rows:
        if currency is None:
            continue
        total_refunded[str(currency).upper()] = Decimal(total or 0)

    # NFT lifecycle
    nft_rows = (
        await db.execute(
            select(Case.nft_state, func.count()).group_by(Case.nft_state)
        )
    ).all()
    nft_states: dict[str, int] = {}
    for state_value, count in nft_rows:
        key = state_value.value if state_value is not None else "none"
        nft_states[key] = int(count)

    # upcoming renewals across all users (≤180 days)
    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(tz=_tz.utc)
    upcoming_cases = (
        await db.execute(
            select(Case)
            .where(Case.renewal_due_at.is_not(None))
            .order_by(Case.renewal_due_at.asc())
            .limit(50)
        )
    ).scalars().all()
    client_ids = {c.client_id for c in upcoming_cases if c.client_id}
    clients: dict[uuid.UUID, User] = {}
    if client_ids:
        clients = {
            u.id: u
            for u in (
                await db.execute(
                    select(User).where(User.id.in_(client_ids))
                )
            ).scalars()
        }
    upcoming: list[AdminUpcomingRenewal] = []
    for c in upcoming_cases:
        due = c.renewal_due_at
        if due is None:
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=_tz.utc)
        days_remaining = (due.date() - now.date()).days
        if days_remaining > 180:
            continue
        owner = clients.get(c.client_id) if c.client_id else None
        upcoming.append(
            AdminUpcomingRenewal(
                case_id=c.id,
                case_number=c.case_number,
                client_email=owner.email if owner else None,
                renewal_due_at=due,
                days_remaining=days_remaining,
                is_overdue=due <= now,
            )
        )

    return AdminAnalyticsSummary(
        cases_total=cases_total,
        cases_open=cases_open,
        cases_closed=cases_closed,
        filings_total=filings_total,
        filings_successful=filings_successful,
        filings_failed=filings_failed,
        filing_success_rate=success_rate,
        total_revenue_by_currency=total_revenue,
        total_refunded_by_currency=total_refunded,
        nft_states=nft_states,
        upcoming_renewals=upcoming,
    )


@router.get("/analytics/timeline", response_model=AdminAnalyticsTimeline)
async def analytics_timeline(
    db: AsyncSession = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> AdminAnalyticsTimeline:
    """System-wide chronological event feed.

    Sources merged in Python (case_created, payment_confirmed,
    payment_refunded, filing_submitted, filing_failed, nft_minted,
    renewal_completed, renewal_reminder_sent). Sorted newest first
    then paginated.
    """
    events: list[AdminTimelineEvent] = []

    all_cases = (await db.execute(select(Case))).scalars().all()
    case_lookup: dict[uuid.UUID, Case] = {c.id: c for c in all_cases}
    client_ids = {c.client_id for c in all_cases if c.client_id}
    clients: dict[uuid.UUID, User] = {}
    if client_ids:
        clients = {
            u.id: u
            for u in (
                await db.execute(
                    select(User).where(User.id.in_(client_ids))
                )
            ).scalars()
        }

    def _email_for_case(case: Case | None) -> str | None:
        if case is None or case.client_id is None:
            return None
        u = clients.get(case.client_id)
        return u.email if u else None

    for case in all_cases:
        owner_email = _email_for_case(case)
        events.append(
            AdminTimelineEvent(
                kind="case_created",
                case_id=case.id,
                case_number=case.case_number,
                client_email=owner_email,
                occurred_at=case.created_at,
                summary=f"Case {case.case_number} created",
                payload={
                    "title": case.title,
                    "jurisdiction": case.jurisdiction,
                },
            )
        )
        if case.nft_mint_tx is not None:
            events.append(
                AdminTimelineEvent(
                    kind="nft_minted",
                    case_id=case.id,
                    case_number=case.case_number,
                    client_email=owner_email,
                    occurred_at=case.updated_at,
                    summary=f"NFT minted for {case.case_number}",
                    payload={
                        "nft_mint": case.nft_mint,
                        "nft_mint_tx": case.nft_mint_tx,
                    },
                )
            )
        if case.last_renewed_at is not None:
            events.append(
                AdminTimelineEvent(
                    kind="renewal_completed",
                    case_id=case.id,
                    case_number=case.case_number,
                    client_email=owner_email,
                    occurred_at=case.last_renewed_at,
                    summary=f"Renewal completed for {case.case_number}",
                    payload={
                        "new_renewal_due_at": (
                            case.renewal_due_at.isoformat()
                            if case.renewal_due_at
                            else None
                        ),
                    },
                )
            )

    # payments
    confirmed_intents = (
        await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.status.in_(
                    (
                        PaymentIntentStatus.confirmed,
                        PaymentIntentStatus.refunded,
                    )
                )
            )
        )
    ).scalars().all()
    draft_ids = {i.case_draft_id for i in confirmed_intents if i.case_draft_id}
    drafts: dict[uuid.UUID, CaseDraft] = {}
    if draft_ids:
        drafts = {
            d.id: d
            for d in (
                await db.execute(
                    select(CaseDraft).where(CaseDraft.id.in_(draft_ids))
                )
            ).scalars()
        }
    for intent in confirmed_intents:
        draft = drafts.get(intent.case_draft_id)
        case = (
            case_lookup.get(draft.promoted_case_id)
            if draft and draft.promoted_case_id
            else None
        )
        owner_email = _email_for_case(case)
        ts = intent.confirmed_at or intent.created_at
        kind = (
            "payment_confirmed"
            if intent.status == PaymentIntentStatus.confirmed
            else "payment_refunded"
        )
        action = (
            "Paid"
            if intent.status == PaymentIntentStatus.confirmed
            else "Refunded"
        )
        case_suffix = f" for {case.case_number}" if case else ""
        events.append(
            AdminTimelineEvent(
                kind=kind,
                case_id=case.id if case else None,
                case_number=case.case_number if case else None,
                client_email=owner_email,
                occurred_at=ts,
                summary=(
                    f"{action} {intent.amount} {intent.currency.upper()}"
                    f"{case_suffix}"
                ),
                payload={
                    "intent_id": str(intent.id),
                    "amount": str(intent.amount),
                    "currency": intent.currency,
                    "provider": intent.provider.value,
                    "intent_kind": (
                        (intent.gateway_metadata or {}).get("intent_kind")
                        or "initial"
                    ),
                },
            )
        )

    # filings
    attempts = (
        await db.execute(select(FilingAttempt))
    ).scalars().all()
    # Make sure all draft IDs from attempts are loaded too.
    attempt_draft_ids = {a.case_draft_id for a in attempts} - set(drafts.keys())
    if attempt_draft_ids:
        extra = {
            d.id: d
            for d in (
                await db.execute(
                    select(CaseDraft).where(CaseDraft.id.in_(attempt_draft_ids))
                )
            ).scalars()
        }
        drafts.update(extra)
    for attempt in attempts:
        draft = drafts.get(attempt.case_draft_id)
        case = (
            case_lookup.get(draft.promoted_case_id)
            if draft and draft.promoted_case_id
            else None
        )
        owner_email = _email_for_case(case)
        ts = attempt.completed_at or attempt.submitted_at or attempt.created_at
        if attempt.status in _SUCCESSFUL_FILING_STATUSES:
            kind = "filing_submitted"
            ref_suffix = (
                f" - ref {attempt.external_reference}"
                if attempt.external_reference
                else ""
            )
            summary = f"{attempt.platform.value} filing submitted{ref_suffix}"
        elif attempt.status in _FAILED_FILING_STATUSES:
            kind = "filing_failed"
            summary = (
                f"{attempt.platform.value} filing failed "
                f"(attempt {attempt.attempt_number})"
            )
        else:
            continue
        events.append(
            AdminTimelineEvent(
                kind=kind,
                case_id=case.id if case else None,
                case_number=case.case_number if case else None,
                client_email=owner_email,
                occurred_at=ts,
                summary=summary,
                payload={
                    "platform": attempt.platform.value,
                    "external_reference": attempt.external_reference,
                    "attempt_number": attempt.attempt_number,
                    "error_message": attempt.error_message,
                },
            )
        )

    # renewal reminders
    reminders = (
        await db.execute(select(RenewalReminder))
    ).scalars().all()
    for r in reminders:
        case = case_lookup.get(r.case_id)
        owner_email = _email_for_case(case)
        suffix = f" for {case.case_number}" if case else ""
        events.append(
            AdminTimelineEvent(
                kind="renewal_reminder_sent",
                case_id=r.case_id,
                case_number=case.case_number if case else None,
                client_email=owner_email,
                occurred_at=r.sent_at,
                summary=f"Renewal reminder ({r.window_days}d) sent{suffix}",
                payload={
                    "window_days": r.window_days,
                    "target_due_at": r.target_due_at.isoformat(),
                    "channels": list(r.channels or []),
                },
            )
        )

    events.sort(key=lambda e: e.occurred_at, reverse=True)
    total = len(events)
    start = page * page_size
    end = start + page_size
    return AdminAnalyticsTimeline(
        events=events[start:end],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Operator key audit log
# ---------------------------------------------------------------------------


@router.get("/operator-keys/audit", response_model=AdminListResponse)
async def operator_key_audit_log(
    db: AsyncSession = Depends(get_db),
    op_kind: str | None = Query(None),
    success: bool | None = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> AdminListResponse:
    """Operator key reads — newest first.

    Each row is one call to ``_load_operator()``: who reached for
    the signing key, for what kind of operation, and whether the
    load succeeded. Filterable by op_kind (sign/verify/inspect) and
    success boolean.
    """
    stmt = select(OperatorKeyAccessLog)
    if op_kind:
        stmt = stmt.where(OperatorKeyAccessLog.op_kind == op_kind)
    if success is not None:
        stmt = stmt.where(OperatorKeyAccessLog.success.is_(success))

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar()
        or 0
    )
    stmt = (
        stmt.order_by(OperatorKeyAccessLog.accessed_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "id": str(r.id),
            "accessed_at": r.accessed_at.isoformat(),
            "caller_context": r.caller_context,
            "op_kind": r.op_kind,
            "success": r.success,
            "note": r.note,
        }
        for r in rows
    ]
    return AdminListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


# ---------------------------------------------------------------------------
# AI cost breakdown
# ---------------------------------------------------------------------------


@router.get("/ai-usage")
async def ai_usage_breakdown(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Token usage + estimated USD cost grouped by model.

    Aggregated from ``agent_session`` because the
    ``total_input_tokens`` / ``total_output_tokens`` columns roll up
    every per-message contribution at orchestrator close-out. Cost is
    estimated from the in-code pricing table; values are USD with
    Decimal precision (no float drift on aggregation).
    """
    rows = (
        await db.execute(
            select(
                AgentSession.model,
                func.sum(AgentSession.total_input_tokens),
                func.sum(AgentSession.total_output_tokens),
                func.count(),
            ).group_by(AgentSession.model)
        )
    ).all()

    per_model: list[dict[str, Any]] = []
    total_in = 0
    total_out = 0
    total_cost = Decimal(0)
    for model_name, sum_in, sum_out, session_count in rows:
        sin = int(sum_in or 0)
        sout = int(sum_out or 0)
        cost = compute_cost_usd(
            model_name=model_name,
            input_tokens=sin,
            output_tokens=sout,
        )
        rate = rate_for_model(model_name)
        per_model.append(
            {
                "model": model_name or "unknown",
                "sessions": int(session_count or 0),
                "input_tokens": sin,
                "output_tokens": sout,
                "input_rate_per_1m_usd": str(rate.input_per_million),
                "output_rate_per_1m_usd": str(rate.output_per_million),
                "estimated_cost_usd": str(cost.quantize(Decimal("0.0001"))),
            }
        )
        total_in += sin
        total_out += sout
        total_cost += cost

    per_model.sort(
        key=lambda r: Decimal(r["estimated_cost_usd"]),
        reverse=True,
    )

    return {
        "totals": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "estimated_cost_usd": str(
                total_cost.quantize(Decimal("0.0001"))
            ),
        },
        "per_model": per_model,
    }

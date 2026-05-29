"""Admin-side system-wide analytics tests.

Covers the contract surface the admin Analytics tab relies on:
- summary returns SYSTEM-WIDE counts (not scoped to caller)
- success_rate denominator excludes pending / retrying
- spend + refund maps grouped by currency
- upcoming_renewals only surfaces cases within 180 days
- timeline merges sources, sorts newest first
- non-admins get 403, anon gets 401
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import (
    CaseDraft,
    CaseDraftStatus,
    FilingAttempt,
    FilingAttemptStatus,
    FilingPlatform,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentProvider,
    PaymentType,
)
from app.cases.models import Case, CaseType
from app.cases.service import create_case
from app.users.models import User
from tests.conftest import auth_headers


async def _seed_draft(
    db: AsyncSession, user: User, *, mark: str = "MarkA"
) -> CaseDraft:
    draft = CaseDraft(
        session_id=uuid.uuid4(),
        user_id=user.id,
        case_type=CaseType.trademark,
        mark_text=mark,
        applicant_name=f"{mark} Ltd",
        applicant_type="legal_entity",
        target_countries=["Germany"],
        selected_platforms=["EUIPO"],
        nice_classes=[9, 42],
        status=CaseDraftStatus.paid,
    )
    db.add(draft)
    await db.flush()
    return draft


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_summary_empty_returns_zeroed_shape(
    client: AsyncClient, admin_user: User
) -> None:
    res = await client.get(
        "/admin/analytics/summary", headers=auth_headers(admin_user)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["cases_total"] == 0
    assert body["filings_total"] == 0
    assert body["filing_success_rate"] is None
    assert body["total_revenue_by_currency"] == {}
    assert body["upcoming_renewals"] == []


@pytest.mark.integration
async def test_summary_counts_system_wide(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    # Admin sees BOTH cases — system-wide.
    await create_case(
        db_session,
        title="ClientCase",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
    )
    await create_case(
        db_session,
        title="AdminCase",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=admin_user.id,
        jurisdiction="European Union",
        nice_classes="9",
    )
    await db_session.commit()

    res = await client.get(
        "/admin/analytics/summary", headers=auth_headers(admin_user)
    )
    body = res.json()
    assert body["cases_total"] == 2


@pytest.mark.integration
async def test_summary_success_rate_excludes_pending(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    draft = await _seed_draft(db_session, client_user)
    statuses = [
        FilingAttemptStatus.submitted,
        FilingAttemptStatus.error,
        FilingAttemptStatus.pending,
    ]
    for n, st in enumerate(statuses, start=1):
        db_session.add(
            FilingAttempt(
                case_draft_id=draft.id,
                platform=FilingPlatform.EUIPO,
                status=st,
                attempt_number=n,
            )
        )
    await db_session.commit()

    res = await client.get(
        "/admin/analytics/summary", headers=auth_headers(admin_user)
    )
    body = res.json()
    assert body["filings_total"] == 3
    assert body["filings_successful"] == 1
    assert body["filings_failed"] == 1
    assert body["filing_success_rate"] == 0.5


@pytest.mark.integration
async def test_summary_revenue_by_currency(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    draft = await _seed_draft(db_session, client_user)
    db_session.add_all(
        [
            PaymentIntent(
                case_draft_id=draft.id,
                payment_type=PaymentType.platform_fee,
                provider=PaymentProvider.stripe,
                amount=Decimal("900.00"),
                currency="EUR",
                status=PaymentIntentStatus.confirmed,
                idempotency_key=f"draft:{draft.id}:k:a1",
                gateway_payment_id="pi_aa",
            ),
            PaymentIntent(
                case_draft_id=draft.id,
                payment_type=PaymentType.platform_fee,
                provider=PaymentProvider.stripe,
                amount=Decimal("265.00"),
                currency="GBP",
                status=PaymentIntentStatus.confirmed,
                idempotency_key=f"draft:{draft.id}:k:a2",
                gateway_payment_id="pi_ab",
            ),
            PaymentIntent(
                case_draft_id=draft.id,
                payment_type=PaymentType.platform_fee,
                provider=PaymentProvider.stripe,
                amount=Decimal("200.00"),
                currency="EUR",
                status=PaymentIntentStatus.refunded,
                idempotency_key=f"draft:{draft.id}:k:a3",
                gateway_payment_id="pi_ac",
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/admin/analytics/summary", headers=auth_headers(admin_user)
    )
    body = res.json()
    rev = body["total_revenue_by_currency"]
    assert Decimal(rev["EUR"]) == Decimal("900.00")
    assert Decimal(rev["GBP"]) == Decimal("265.00")
    ref = body["total_refunded_by_currency"]
    assert Decimal(ref["EUR"]) == Decimal("200.00")


@pytest.mark.integration
async def test_summary_upcoming_renewals_window(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    soon = await create_case(
        db_session,
        title="SoonRenew",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
        filing_date=date.today() - timedelta(days=10),
    )
    soon.renewal_due_at = datetime.now(tz=timezone.utc) + timedelta(days=60)
    far = await create_case(
        db_session,
        title="FarRenew",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
        filing_date=date.today() - timedelta(days=10),
    )
    far.renewal_due_at = datetime.now(tz=timezone.utc) + timedelta(
        days=365 * 5
    )
    await db_session.commit()

    res = await client.get(
        "/admin/analytics/summary", headers=auth_headers(admin_user)
    )
    body = res.json()
    case_numbers = {r["case_number"] for r in body["upcoming_renewals"]}
    assert soon.case_number in case_numbers
    assert far.case_number not in case_numbers


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_timeline_sorts_newest_first(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    older = await create_case(
        db_session,
        title="OlderCase",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
    )
    older.created_at = datetime.now(tz=timezone.utc) - timedelta(days=10)
    newer = await create_case(
        db_session,
        title="NewerCase",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
    )
    newer.created_at = datetime.now(tz=timezone.utc) - timedelta(days=1)
    await db_session.commit()

    res = await client.get(
        "/admin/analytics/timeline", headers=auth_headers(admin_user)
    )
    body = res.json()
    created = [e for e in body["events"] if e["kind"] == "case_created"]
    assert created[0]["case_number"] == newer.case_number


@pytest.mark.integration
async def test_timeline_includes_payment_and_filing_events(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    draft = await _seed_draft(db_session, client_user)
    db_session.add(
        PaymentIntent(
            case_draft_id=draft.id,
            payment_type=PaymentType.platform_fee,
            provider=PaymentProvider.stripe,
            amount=Decimal("900.00"),
            currency="EUR",
            status=PaymentIntentStatus.confirmed,
            confirmed_at=datetime.now(tz=timezone.utc),
            idempotency_key=f"draft:{draft.id}:p",
            gateway_payment_id="pi_tl",
        )
    )
    db_session.add(
        FilingAttempt(
            case_draft_id=draft.id,
            platform=FilingPlatform.EUIPO,
            status=FilingAttemptStatus.submitted,
            attempt_number=1,
            external_reference="EUTM-TEST-123",
            submitted_at=datetime.now(tz=timezone.utc),
        )
    )
    await db_session.commit()

    res = await client.get(
        "/admin/analytics/timeline", headers=auth_headers(admin_user)
    )
    kinds = {e["kind"] for e in res.json()["events"]}
    assert "payment_confirmed" in kinds
    assert "filing_submitted" in kinds


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_summary_forbidden_for_client(
    client: AsyncClient, client_user: User
) -> None:
    res = await client.get(
        "/admin/analytics/summary", headers=auth_headers(client_user)
    )
    assert res.status_code == 403


@pytest.mark.integration
async def test_timeline_unauthorised(client: AsyncClient) -> None:
    res = await client.get("/admin/analytics/timeline")
    assert res.status_code == 401


@pytest.mark.integration
async def test_summary_unauthorised(client: AsyncClient) -> None:
    res = await client.get("/admin/analytics/summary")
    assert res.status_code == 401

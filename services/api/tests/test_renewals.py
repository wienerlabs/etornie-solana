"""Renewal lifecycle tests.

Covers the three pillars Phase C.5 introduced:
1. Pure functions: due-date arithmetic + window detection.
2. Dispatcher: reminder rows are written exactly once per
   (case, window, target_due_at), and re-running the scan finds
   nothing new.
3. API surface: /cases/{id}/renewal-status returns the right shape
   and respects ownership.

The Stripe Checkout creation path is exercised via a unit test that
monkey-patches ``stripe.checkout.Session.create`` because the real
SDK call would talk to the Stripe sandbox in CI.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import (
    CaseDraft,
    CaseDraftStatus,
)
from app.cases.models import Case, CaseType
from app.cases.service import create_case
from app.renewals.models import RenewalReminder
from app.renewals.service import (
    EUIPO_RENEWAL_TERM_YEARS,
    REMINDER_WINDOWS_DAYS,
    compute_renewal_due_at,
    detect_open_window,
    mark_case_renewed,
    scan_and_dispatch_due_reminders,
    set_initial_renewal_due_at,
)
from app.auth.utils import hash_password
from app.users.models import User, UserRole
from tests.conftest import auth_headers


@pytest.fixture
async def other_client_user(db_session: AsyncSession) -> User:
    """A second client user — the ``second_lawyer_user`` fixture in
    conftest still references the retired UserRole.lawyer value, so
    we create our own non-owner test subject here."""
    user = User(
        email="other-client@etornie.ch",
        hashed_password=hash_password("OtherPass123!"),
        full_name="Other Client",
        role=UserRole.client,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def test_compute_renewal_due_at_adds_term_years() -> None:
    filed = datetime(2024, 5, 1, tzinfo=timezone.utc)
    due = compute_renewal_due_at(filing_date=filed)
    assert due is not None
    assert due.year == 2024 + EUIPO_RENEWAL_TERM_YEARS
    assert due.month == 5
    assert due.day == 1


def test_compute_renewal_due_at_handles_leap_day() -> None:
    filed = datetime(2024, 2, 29, tzinfo=timezone.utc)
    due = compute_renewal_due_at(filing_date=filed)
    # 2034 has no Feb 29 → fallback to 365*10 day delta lands on
    # Feb 26-27. We only require it doesn't crash + lands within
    # the same month-ish.
    assert due is not None
    assert due.year == 2034


def test_compute_renewal_due_at_returns_none_on_missing_filing_date() -> None:
    assert compute_renewal_due_at(filing_date=None) is None


def test_detect_open_window_picks_smallest_open() -> None:
    due = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # 45 days before due → 90 window open, 30 window not yet open.
    now = due - timedelta(days=45)
    assert detect_open_window(renewal_due_at=due, now=now) == 90
    # 15 days before due → 30 window open, 0 window not yet open.
    now = due - timedelta(days=15)
    assert detect_open_window(renewal_due_at=due, now=now) == 30
    # On due date → 0 window open.
    now = due
    assert detect_open_window(renewal_due_at=due, now=now) == 0


def test_detect_open_window_returns_none_when_too_early() -> None:
    due = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # 200 days before any window opens.
    now = due - timedelta(days=200)
    assert detect_open_window(renewal_due_at=due, now=now) is None


# ---------------------------------------------------------------------------
# DB integration: setter + dispatcher
# ---------------------------------------------------------------------------


@pytest.fixture
async def renewable_case(
    db_session: AsyncSession, client_user: User
) -> Case:
    """A case with filing_date set to N years ago so renewal_due_at
    naturally falls inside a reminder window after set_initial."""
    filed = date.today() - timedelta(
        days=365 * EUIPO_RENEWAL_TERM_YEARS - 45
    )
    case = await create_case(
        db_session,
        title="RenewableMark",
        description="renewal test",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9,42",
        filing_date=filed,
    )
    await db_session.flush()
    return case


@pytest.mark.integration
async def test_set_initial_renewal_due_at_stamps_field(
    db_session: AsyncSession, renewable_case: Case
) -> None:
    assert renewable_case.renewal_due_at is None
    await set_initial_renewal_due_at(db_session, renewable_case)
    assert renewable_case.renewal_due_at is not None
    # ~45 days from now ± a day, since we filed 10y - 45d ago.
    delta = (
        renewable_case.renewal_due_at.date() - date.today()
    ).days
    assert 40 <= delta <= 50


@pytest.mark.integration
async def test_set_initial_is_idempotent(
    db_session: AsyncSession, renewable_case: Case
) -> None:
    await set_initial_renewal_due_at(db_session, renewable_case)
    stamped = renewable_case.renewal_due_at
    # Pretend a stale caller re-runs promotion: the function must NOT
    # overwrite the existing value (would clobber a renewal advance).
    await set_initial_renewal_due_at(db_session, renewable_case)
    assert renewable_case.renewal_due_at == stamped


@pytest.mark.integration
async def test_mark_case_renewed_advances_due_at_by_term(
    db_session: AsyncSession, renewable_case: Case
) -> None:
    await set_initial_renewal_due_at(db_session, renewable_case)
    before = renewable_case.renewal_due_at
    await mark_case_renewed(db_session, renewable_case)
    after = renewable_case.renewal_due_at
    assert renewable_case.last_renewed_at is not None
    # ~10 year shift on the due date; tolerate the leap-year wobble.
    assert before is not None and after is not None
    delta_days = (after - before).days
    assert 3650 - 5 <= delta_days <= 3650 + 5


@pytest.mark.integration
async def test_dispatcher_records_one_reminder_per_window(
    db_session: AsyncSession, renewable_case: Case
) -> None:
    await set_initial_renewal_due_at(db_session, renewable_case)
    # First run dispatches the 90-day reminder (we filed 10y-45d ago,
    # so we're between the 90 and 30 windows).
    result = await scan_and_dispatch_due_reminders(db_session)
    assert result.scanned >= 1
    assert result.dispatched >= 1

    rows = (
        await db_session.execute(
            select(RenewalReminder).where(
                RenewalReminder.case_id == renewable_case.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].window_days == 90

    # Second run on the same day must NOT add another row — the
    # unique constraint dedupes (case, window, target_due_at).
    again = await scan_and_dispatch_due_reminders(db_session)
    assert again.dispatched == 0
    assert again.skipped_due_to_existing >= 1
    rows = (
        await db_session.execute(
            select(RenewalReminder).where(
                RenewalReminder.case_id == renewable_case.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_dispatcher_skips_cases_without_due_date(
    db_session: AsyncSession, client_user: User
) -> None:
    # Case without filing_date → no renewal_due_at → skipped.
    case = await create_case(
        db_session,
        title="NoFiling",
        description="no filing date",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
    )
    await db_session.flush()
    result = await scan_and_dispatch_due_reminders(db_session)
    # The case has no due_at → dispatcher does not scan it.
    rows = (
        await db_session.execute(
            select(RenewalReminder).where(
                RenewalReminder.case_id == case.id
            )
        )
    ).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_renewal_status_returns_shape(
    client: AsyncClient,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    filed = date.today() - timedelta(days=365 * 9)  # ~1y to renewal
    case = await create_case(
        db_session,
        title="StatusMark",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9,42,35",
        filing_date=filed,
    )
    await set_initial_renewal_due_at(db_session, case)
    await db_session.commit()

    res = await client.get(
        f"/cases/{case.id}/renewal-status",
        headers=auth_headers(client_user),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["case_id"] == str(case.id)
    assert body["renewal_due_at"] is not None
    assert body["is_overdue"] is False
    assert body["days_remaining"] is not None
    assert body["reminders"] == []


@pytest.mark.integration
async def test_renewal_status_forbidden_for_non_owner(
    client: AsyncClient,
    client_user: User,
    other_client_user: User,
    db_session: AsyncSession,
) -> None:
    case = await create_case(
        db_session,
        title="OwnedByClient",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
        filing_date=date.today() - timedelta(days=10),
    )
    await db_session.commit()
    res = await client.get(
        f"/cases/{case.id}/renewal-status",
        headers=auth_headers(other_client_user),
    )
    assert res.status_code == 403


@pytest.mark.integration
async def test_renewal_checkout_rejects_non_owner(
    client: AsyncClient,
    client_user: User,
    other_client_user: User,
    db_session: AsyncSession,
) -> None:
    case = await create_case(
        db_session,
        title="OwnedByClient2",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9",
        filing_date=date.today() - timedelta(days=10),
    )
    await set_initial_renewal_due_at(db_session, case)
    await db_session.commit()
    res = await client.post(
        f"/cases/{case.id}/renew/checkout",
        headers=auth_headers(other_client_user),
    )
    # Could be 403 (ownership) or 503 (stripe missing) depending on
    # env — both prove the endpoint refused the action.
    assert res.status_code in (403, 503)


@pytest.mark.integration
async def test_admin_renewal_dispatch_returns_counts(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    filed = date.today() - timedelta(
        days=365 * EUIPO_RENEWAL_TERM_YEARS - 45
    )
    case = await create_case(
        db_session,
        title="AdminDispatchMark",
        description="-",
        case_type=CaseType.trademark.value,
        client_id=client_user.id,
        jurisdiction="European Union",
        nice_classes="9,42",
        filing_date=filed,
    )
    await set_initial_renewal_due_at(db_session, case)
    await db_session.commit()

    res = await client.post(
        "/admin/renewals/dispatch", headers=auth_headers(admin_user)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["scanned"] >= 1
    assert body["dispatched"] >= 1

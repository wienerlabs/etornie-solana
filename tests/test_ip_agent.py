"""Tests for the IP Agent — deadline tracking and auto-notification."""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ip_agent.service import (
    DAY_TEMPLATE_NAMES,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_MINUTES,
    MINUTE_TEMPLATE_NAMES,
    create_deadline_notifications,
    run_ip_agent,
    scan_upcoming_deadlines,
)
from app.cases.models import CaseStatus
from app.cases.service import create_case
from app.notifications.models import Notification, NotificationStatus, NotificationType
from app.users.models import User, UserRole
from sqlalchemy import select
from tests.conftest import _create_user_in_db, auth_headers

# Turkey timezone (UTC+3) — must match the one used in the IP agent service
TZ_TR = timezone(timedelta(hours=3))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_case(
    db: AsyncSession,
    client_user: User,
    lawyer_user: User | None,
    *,
    deadline_days: int | None = 30,
    deadline_time: time | None = None,
    status: str = "open",
    title: str = "Test Case",
) -> object:
    """Create a case with a deadline N days from today.

    If ``deadline_time`` is provided the case gets both a deadline date and
    a deadline_time, enabling minute-based scanning.
    """
    deadline = None
    if deadline_days is not None:
        deadline = date.today() + timedelta(days=deadline_days)

    case = await create_case(
        db,
        title=title,
        description="Test case for IP agent",
        case_type="trademark",
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id if lawyer_user else None,
        jurisdiction="Turkey",
        deadline=deadline,
        deadline_time=deadline_time,
    )

    if status != "open":
        case.status = CaseStatus(status)
        await db.flush()
        await db.refresh(case)

    return case


# ---------------------------------------------------------------------------
# 1. scan_upcoming_deadlines — finds 30-day cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_deadlines_finds_30_day_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(db_session, client_user, lawyer_user, deadline_days=30)

    matches = await scan_upcoming_deadlines(db_session, reminder_days=[30, 7, 1])

    assert len(matches) == 1
    assert matches[0]["days_remaining"] == 30


# ---------------------------------------------------------------------------
# 2. scan_upcoming_deadlines — finds 7-day cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_deadlines_finds_7_day_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(db_session, client_user, lawyer_user, deadline_days=7)

    matches = await scan_upcoming_deadlines(db_session, reminder_days=[30, 7, 1])

    assert len(matches) == 1
    assert matches[0]["days_remaining"] == 7


# ---------------------------------------------------------------------------
# 3. scan_upcoming_deadlines — finds 1-day cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_deadlines_finds_1_day_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(db_session, client_user, lawyer_user, deadline_days=1)

    matches = await scan_upcoming_deadlines(db_session, reminder_days=[30, 7, 1])

    assert len(matches) == 1
    assert matches[0]["days_remaining"] == 1


# ---------------------------------------------------------------------------
# 4. scan_upcoming_deadlines — ignores closed cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_deadlines_ignores_closed_cases(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(
        db_session, client_user, lawyer_user, deadline_days=7, status="closed"
    )

    matches = await scan_upcoming_deadlines(db_session, reminder_days=[30, 7, 1])

    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 5. scan_upcoming_deadlines — ignores cases without deadline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_deadlines_ignores_no_deadline(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(
        db_session, client_user, lawyer_user, deadline_days=None
    )

    matches = await scan_upcoming_deadlines(db_session, reminder_days=[30, 7, 1])

    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 6. scan_upcoming_deadlines — ignores other day intervals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_deadlines_ignores_other_days(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(db_session, client_user, lawyer_user, deadline_days=15)

    matches = await scan_upcoming_deadlines(db_session, reminder_days=[30, 7, 1])

    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 7. create_deadline_notifications — creates for both lawyer and client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_notifications_for_lawyer_and_client(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    case = await _make_case(db_session, client_user, lawyer_user, deadline_days=1)

    matches = await scan_upcoming_deadlines(db_session, reminder_days=DEFAULT_REMINDER_DAYS)
    assert len(matches) == 1

    notifications = await create_deadline_notifications(db_session, matches)

    assert len(notifications) == 2

    phones = {n.recipient_phone for n in notifications}
    assert lawyer_user.phone in phones
    assert client_user.phone in phones

    # Verify notifications use template type with correct template name
    for n in notifications:
        assert n.message_type == NotificationType.template
        assert n.template_name == DAY_TEMPLATE_NAMES[1]
        assert case.case_number in n.message_body
        assert case.title in n.message_body


# ---------------------------------------------------------------------------
# 8. create_deadline_notifications — skips users without phone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_notifications_skips_no_phone(
    db_session: AsyncSession,
    client_user: User,
) -> None:
    # Create a lawyer without phone number
    lawyer_no_phone = await _create_user_in_db(
        db_session,
        email="nophone@etornie.ch",
        password="NoPhone123!",
        full_name="No Phone Lawyer",
        role=UserRole.lawyer,
        phone=None,
    )

    await _make_case(db_session, client_user, lawyer_no_phone, deadline_days=1)

    matches = await scan_upcoming_deadlines(db_session, reminder_days=DEFAULT_REMINDER_DAYS)
    notifications = await create_deadline_notifications(db_session, matches)

    # Only client (who has a phone) should get a notification
    assert len(notifications) == 1
    assert notifications[0].recipient_phone == client_user.phone


# ---------------------------------------------------------------------------
# 9. create_deadline_notifications — prevents duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_notifications_prevents_duplicates(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(db_session, client_user, lawyer_user, deadline_days=1)

    matches = await scan_upcoming_deadlines(db_session, reminder_days=DEFAULT_REMINDER_DAYS)

    first_run = await create_deadline_notifications(db_session, matches)
    assert len(first_run) == 2

    # Run again — should not create duplicates
    matches2 = await scan_upcoming_deadlines(db_session, reminder_days=DEFAULT_REMINDER_DAYS)
    second_run = await create_deadline_notifications(db_session, matches2)
    assert len(second_run) == 0


# ---------------------------------------------------------------------------
# 10. run_ip_agent — full cycle end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_ip_agent_full_cycle(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    await _make_case(
        db_session, client_user, lawyer_user,
        deadline_days=1, title="Urgent Patent"
    )
    await _make_case(
        db_session, client_user, lawyer_user,
        deadline_days=1, title="Trademark Filing"
    )
    # This one should NOT be picked up (15 days not in DEFAULT_REMINDER_DAYS)
    await _make_case(
        db_session, client_user, lawyer_user,
        deadline_days=15, title="Other Case"
    )

    result = await run_ip_agent(db_session)

    assert result["scanned_cases"] == 2
    assert result["deadlines_found"] == 2
    # 2 cases x 2 users (lawyer + client) = 4 notifications
    assert result["notifications_created"] == 4
    assert len(result["alerts"]) == 2

    # Verify notifications actually exist in DB
    db_result = await db_session.execute(select(Notification))
    all_notifications = list(db_result.scalars().all())
    assert len(all_notifications) == 4


# ---------------------------------------------------------------------------
# 11. POST /agents/ip/scan-deadlines — admin only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_deadlines_endpoint_admin_only(
    client: AsyncClient,
    admin_user: User,
    lawyer_user: User,
    client_user: User,
) -> None:
    # Admin should succeed
    response = await client.post(
        "/agents/ip/scan-deadlines",
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 200

    # Lawyer should be forbidden
    response = await client.post(
        "/agents/ip/scan-deadlines",
        headers=auth_headers(lawyer_user),
    )
    assert response.status_code == 403

    # Client should be forbidden
    response = await client.post(
        "/agents/ip/scan-deadlines",
        headers=auth_headers(client_user),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 12. GET /agents/ip/upcoming-deadlines — RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upcoming_deadlines_endpoint_rbac(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    lawyer_user: User,
    client_user: User,
    second_lawyer_user: User,
) -> None:
    # Create a case assigned to lawyer_user
    case = await _make_case(
        db_session, client_user, lawyer_user,
        deadline_days=10, title="Lawyer1 Case"
    )
    await db_session.commit()

    # Admin sees all
    response = await client.get(
        "/agents/ip/upcoming-deadlines",
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1

    # Assigned lawyer sees their case
    response = await client.get(
        "/agents/ip/upcoming-deadlines",
        headers=auth_headers(lawyer_user),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    for item in data["deadlines"]:
        assert item["lawyer_name"] == lawyer_user.full_name

    # Second lawyer (no cases assigned) sees nothing
    response = await client.get(
        "/agents/ip/upcoming-deadlines",
        headers=auth_headers(second_lawyer_user),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0

    # Client should be forbidden
    response = await client.get(
        "/agents/ip/upcoming-deadlines",
        headers=auth_headers(client_user),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 13. Minute scan — finds case 30 minutes from now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_minute_deadlines_finds_30_min_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=30)

    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="30-min Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=DEFAULT_REMINDER_MINUTES
    )

    assert len(matches) == 1
    assert matches[0]["interval_type"] == "minutes"
    assert matches[0]["interval_value"] == 30


# ---------------------------------------------------------------------------
# 14. Minute scan — finds case 10 minutes from now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_minute_deadlines_finds_10_min_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=10)

    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="10-min Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=DEFAULT_REMINDER_MINUTES
    )

    assert len(matches) == 1
    assert matches[0]["interval_type"] == "minutes"
    assert matches[0]["interval_value"] == 10


# ---------------------------------------------------------------------------
# 15. Minute scan — finds case 5 minutes from now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_minute_deadlines_finds_5_min_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=5)

    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="5-min Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=DEFAULT_REMINDER_MINUTES
    )

    assert len(matches) == 1
    assert matches[0]["interval_type"] == "minutes"
    assert matches[0]["interval_value"] == 5


# ---------------------------------------------------------------------------
# 16. Minute scan — finds case 1 minute from now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_minute_deadlines_finds_1_min_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=1)

    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="1-min Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=DEFAULT_REMINDER_MINUTES
    )

    assert len(matches) == 1
    assert matches[0]["interval_type"] == "minutes"
    assert matches[0]["interval_value"] == 1


# ---------------------------------------------------------------------------
# 17. Day scan still works for case with only deadline (no deadline_time)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_day_scan_still_works_without_deadline_time(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    """Cases with only a deadline date (no deadline_time) should still
    be found by the day-based scan and should NOT appear in minute scan."""
    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=7,
        deadline_time=None,
        title="Day-only Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[30, 7, 1], reminder_minutes=[30, 10, 5, 1]
    )

    assert len(matches) == 1
    assert matches[0]["interval_type"] == "days"
    assert matches[0]["days_remaining"] == 7


# ---------------------------------------------------------------------------
# 18. Minute scan — creates notifications for both lawyer and client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minute_notifications_created_for_lawyer_and_client(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=10)

    case = await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="Minute Notify Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=DEFAULT_REMINDER_MINUTES
    )
    assert len(matches) == 1

    notifications = await create_deadline_notifications(db_session, matches)

    assert len(notifications) == 2

    phones = {n.recipient_phone for n in notifications}
    assert lawyer_user.phone in phones
    assert client_user.phone in phones

    # Verify notifications use template type with correct template name
    for n in notifications:
        assert n.message_type == NotificationType.template
        assert n.template_name == MINUTE_TEMPLATE_NAMES[10]
        assert case.case_number in n.message_body
        assert "10 dakika" in n.message_body


# ---------------------------------------------------------------------------
# 19. Minute scan — prevents duplicate minute notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minute_notifications_prevents_duplicates(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=5)

    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="Dup Minute Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=DEFAULT_REMINDER_MINUTES
    )
    first_run = await create_deadline_notifications(db_session, matches)
    assert len(first_run) == 2

    # Run again — should not create duplicates
    matches2 = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=DEFAULT_REMINDER_MINUTES
    )
    second_run = await create_deadline_notifications(db_session, matches2)
    assert len(second_run) == 0


# ---------------------------------------------------------------------------
# 20. Minute scan — case with deadline_time NOT near any interval is ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minute_scan_ignores_non_matching_intervals(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(timezone.utc)
    # 15 minutes from now — doesn't match any of [30, 10, 5, 1]
    target_dt = now + timedelta(minutes=15)

    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="15-min Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=[], reminder_minutes=[30, 10, 5, 1]
    )

    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 21. Mixed scan — day and minute cases found together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_day_and_minute_scan(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    """Both day-based and minute-based cases are returned in one scan."""
    # Day-based case
    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=1,
        title="Day Case",
    )

    # Minute-based case
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=30)
    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="Minute Case",
    )

    matches = await scan_upcoming_deadlines(
        db_session, reminder_days=DEFAULT_REMINDER_DAYS, reminder_minutes=DEFAULT_REMINDER_MINUTES
    )

    assert len(matches) == 2

    interval_types = {m["interval_type"] for m in matches}
    assert "days" in interval_types
    assert "minutes" in interval_types


# ---------------------------------------------------------------------------
# 22. run_ip_agent — full cycle with minute-based case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_ip_agent_with_minute_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> None:
    now = datetime.now(TZ_TR)
    target_dt = now + timedelta(minutes=5)

    await _make_case(
        db_session,
        client_user,
        lawyer_user,
        deadline_days=0,
        deadline_time=target_dt.time(),
        title="Urgent Minute Patent",
    )

    result = await run_ip_agent(db_session)

    assert result["deadlines_found"] >= 1
    assert result["notifications_created"] >= 2

    # Check that at least one alert has interval_type "minutes"
    minute_alerts = [
        a for a in result["alerts"] if a["interval_type"] == "minutes"
    ]
    assert len(minute_alerts) >= 1
    assert minute_alerts[0]["interval_value"] == 5

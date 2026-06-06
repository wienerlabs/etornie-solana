"""Build the iCalendar feed and manage the per-user feed token."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from icalendar import Alarm, Calendar, Event
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseStatus
from app.config import settings
from app.users.models import User

_PRODID = "-//Etornie//IP Deadlines//EN"
_CALENDAR_NAME = "Etornie IP Deadlines"

# Reminders fired ahead of each deadline, mirroring the renewal
# dispatcher's intent that counsel gets advance warning.
_ALARM_OFFSETS: tuple[timedelta, ...] = (
    timedelta(days=-7),
    timedelta(days=-1),
)


def generate_token() -> str:
    """A URL-safe, unguessable feed token (fits the 64-char column)."""

    return secrets.token_urlsafe(32)


async def get_user_by_feed_token(
    db: AsyncSession, token: str
) -> User | None:
    if not token:
        return None
    return (
        await db.execute(
            select(User).where(User.calendar_feed_token == token)
        )
    ).scalar_one_or_none()


async def ensure_token(db: AsyncSession, user: User) -> str:
    """Return the user's feed token, creating one on first use."""

    if not user.calendar_feed_token:
        user.calendar_feed_token = generate_token()
        await db.flush()
    return user.calendar_feed_token


async def rotate_token(db: AsyncSession, user: User) -> str:
    """Issue a fresh token, revoking the previous feed URL."""

    user.calendar_feed_token = generate_token()
    await db.flush()
    return user.calendar_feed_token


async def disable_feed(db: AsyncSession, user: User) -> None:
    user.calendar_feed_token = None
    await db.flush()


def feed_url(token: str) -> str:
    base = settings.api_public_url.rstrip("/")
    return f"{base}/calendar/feed/{token}.ics"


async def _cases_for(db: AsyncSession, user: User) -> list[Case]:
    """Cases the user is involved in (as client or assigned counsel)."""

    stmt = select(Case).where(
        or_(Case.client_id == user.id, Case.assigned_lawyer_id == user.id)
    )
    return list((await db.execute(stmt)).scalars().all())


def _with_alarms(event: Event, summary: str) -> None:
    for offset in _ALARM_OFFSETS:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", summary)
        alarm.add("trigger", offset)
        event.add_component(alarm)


def _build_event(
    *,
    uid: str,
    summary: str,
    start,
    all_day: bool,
    description: str,
    last_modified: datetime | None,
    stamp: datetime,
) -> Event:
    event = Event()
    event.add("uid", uid)
    event.add("summary", summary)
    event.add("dtstart", start)
    # A bounded end keeps every client happy: all-day events span one day,
    # timed events one hour.
    event.add("dtend", start + timedelta(days=1 if all_day else 0, hours=0 if all_day else 1))
    event.add("dtstamp", stamp)
    if last_modified is not None:
        event.add("last-modified", last_modified)
    event.add("description", description)
    event.add("transp", "TRANSPARENT")
    _with_alarms(event, summary)
    return event


async def build_feed(db: AsyncSession, user: User) -> bytes:
    """Render the user's deadlines + renewals as an iCalendar document."""

    cal = Calendar()
    cal.add("prodid", _PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", _CALENDAR_NAME)
    # Hint subscribed clients to refresh roughly hourly.
    cal.add("x-published-ttl", "PT1H")
    cal.add("refresh-interval;value=duration", "PT1H")

    stamp = datetime.now(timezone.utc)

    for case in await _cases_for(db, user):
        label = f"{case.title} ({case.case_number})"
        jurisdiction = case.jurisdiction or "n/a"

        if case.deadline is not None:
            if case.deadline_time is not None:
                start = datetime.combine(
                    case.deadline, case.deadline_time, tzinfo=timezone.utc
                )
                all_day = False
            else:
                start = case.deadline  # date -> all-day VEVENT
                all_day = True
            cal.add_component(
                _build_event(
                    uid=f"{case.id}-deadline@etornie",
                    summary=f"IP deadline: {label}",
                    start=start,
                    all_day=all_day,
                    description=(
                        f"Deadline for IP case {case.case_number}. "
                        f"Jurisdiction: {jurisdiction}."
                    ),
                    last_modified=case.updated_at,
                    stamp=stamp,
                )
            )

        if case.renewal_due_at is not None and case.status != CaseStatus.closed:
            cal.add_component(
                _build_event(
                    uid=f"{case.id}-renewal@etornie",
                    summary=f"Renewal due: {label}",
                    start=case.renewal_due_at,
                    all_day=False,
                    description=(
                        f"Renewal due for IP case {case.case_number}. "
                        f"Jurisdiction: {jurisdiction}."
                    ),
                    last_modified=case.updated_at,
                    stamp=stamp,
                )
            )

    return cal.to_ical()

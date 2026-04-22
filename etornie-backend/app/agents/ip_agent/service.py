"""IP Agent — Deadline tracking and auto-notification service.

Scans active cases for upcoming deadlines and creates WhatsApp
notifications for the assigned lawyer and case client.

Supports two modes:
- Day-based: cases with only ``deadline`` (date) — checks against
  configured day intervals (e.g. 30, 7, 1 days).
- Minute-based: cases with both ``deadline`` and ``deadline_time`` —
  combines them into a datetime and checks against configured minute
  intervals (e.g. 30, 10, 5, 1 minutes).
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone

# Turkey timezone (UTC+3)
TZ_TR = timezone(timedelta(hours=3))

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.ip_agent.models import AgentConfig
from app.agents.ip_agent.templates import DEADLINE_TEMPLATES, MINUTE_TEMPLATES
from app.cases.models import Case, CaseStatus
from app.notifications.models import Notification, NotificationStatus, NotificationType
from app.notifications.service import create_notification
from app.users.models import User

logger = logging.getLogger(__name__)

IP_AGENT_NAME = "ip_agent"
DEFAULT_REMINDER_DAYS = [10, 5, 1]
DEFAULT_REMINDER_MINUTES = [30, 10, 5, 1]

MINUTE_TOLERANCE = 1.5

# WhatsApp template name mapping
DAY_TEMPLATE_NAMES: dict[int, str] = {
    10: "deadline_10_gun",
    5: "deadline_5_gun",
    1: "deadline_1_gun",
}

MINUTE_TEMPLATE_NAMES: dict[int, str] = {
    30: "deadline_30_dakika",
    10: "deadline_10_dakika",
    5: "deadline_5_dakika",
    1: "deadline_1_dakika",
}


async def _get_agent_config(db: AsyncSession) -> AgentConfig | None:
    """Load the agent config row, or None if it does not exist."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_name == IP_AGENT_NAME)
    )
    return result.scalar_one_or_none()


async def _get_reminder_days(db: AsyncSession) -> list[int]:
    """Load configured reminder days from the database, falling back to defaults."""
    config = await _get_agent_config(db)
    if config is None or not config.is_enabled:
        if config is not None and not config.is_enabled:
            return []
        return list(DEFAULT_REMINDER_DAYS)

    try:
        return [int(d.strip()) for d in config.reminder_days.split(",") if d.strip()]
    except ValueError:
        logger.warning("Invalid reminder_days in agent config, using defaults")
        return list(DEFAULT_REMINDER_DAYS)


async def _get_reminder_minutes(db: AsyncSession) -> list[int]:
    """Load configured reminder minutes from the database, falling back to defaults."""
    config = await _get_agent_config(db)
    if config is None or not config.is_enabled:
        if config is not None and not config.is_enabled:
            return []
        return list(DEFAULT_REMINDER_MINUTES)

    try:
        return [int(m.strip()) for m in config.reminder_minutes.split(",") if m.strip()]
    except ValueError:
        logger.warning("Invalid reminder_minutes in agent config, using defaults")
        return list(DEFAULT_REMINDER_MINUTES)


async def _scan_day_deadlines(
    db: AsyncSession,
    reminder_days: list[int],
) -> list[dict]:
    """Scan cases with only a deadline date (no deadline_time) for day-based matches."""
    if not reminder_days:
        return []

    today = datetime.now(TZ_TR).date()
    target_dates = {days: today + timedelta(days=days) for days in reminder_days}

    result = await db.execute(
        select(Case)
        .where(
            and_(
                Case.status != CaseStatus.closed,
                Case.deadline.isnot(None),
                Case.deadline_time.is_(None),
                Case.deadline.in_(list(target_dates.values())),
            )
        )
        .options(
            selectinload(Case.client),
            selectinload(Case.assigned_lawyer),
        )
    )
    cases = list(result.scalars().all())

    matches: list[dict] = []
    for case in cases:
        days_remaining = (case.deadline - today).days
        matches.append({
            "case": case,
            "days_remaining": days_remaining,
            "interval_type": "days",
            "interval_value": days_remaining,
            "lawyer": case.assigned_lawyer,
            "client": case.client,
        })

    return matches


async def _scan_minute_deadlines(
    db: AsyncSession,
    reminder_minutes: list[int],
) -> list[dict]:
    """Scan cases with both deadline and deadline_time for minute-based matches."""
    if not reminder_minutes:
        return []

    now = datetime.now(TZ_TR)

    result = await db.execute(
        select(Case)
        .where(
            and_(
                Case.status != CaseStatus.closed,
                Case.deadline.isnot(None),
                Case.deadline_time.isnot(None),
            )
        )
        .options(
            selectinload(Case.client),
            selectinload(Case.assigned_lawyer),
        )
    )
    cases = list(result.scalars().all())

    matches: list[dict] = []
    for case in cases:
        case_deadline_dt = datetime.combine(
            case.deadline, case.deadline_time, tzinfo=TZ_TR
        )
        minutes_remaining = (case_deadline_dt - now).total_seconds() / 60

        for interval in reminder_minutes:
            if abs(minutes_remaining - interval) <= MINUTE_TOLERANCE:
                days_remaining = (case.deadline - now.date()).days
                matches.append({
                    "case": case,
                    "days_remaining": days_remaining,
                    "interval_type": "minutes",
                    "interval_value": interval,
                    "lawyer": case.assigned_lawyer,
                    "client": case.client,
                })
                break  # one match per case is enough

    return matches


async def scan_upcoming_deadlines(
    db: AsyncSession,
    reminder_days: list[int] | None = None,
    reminder_minutes: list[int] | None = None,
) -> list[dict]:
    """Scan all active cases for upcoming deadlines.

    Returns list of dicts containing case, days_remaining, interval_type,
    interval_value, lawyer, and client for cases where the deadline matches
    a configured interval.

    Two scans are performed:
    - Day scan: cases with ``deadline`` only (no ``deadline_time``)
    - Minute scan: cases with both ``deadline`` and ``deadline_time``
    """
    if reminder_days is None:
        reminder_days = await _get_reminder_days(db)
    if reminder_minutes is None:
        reminder_minutes = await _get_reminder_minutes(db)

    day_matches = await _scan_day_deadlines(db, reminder_days)
    minute_matches = await _scan_minute_deadlines(db, reminder_minutes)

    return day_matches + minute_matches


def _format_message(
    template: str,
    case: Case,
    lawyer: User | None,
    client: User | None,
    deadline_time: str | None = None,
) -> str:
    """Format a template string with case and user data."""
    return template.format(
        lawyer_name=lawyer.full_name if lawyer else "",
        client_name=client.full_name if client else "",
        case_number=case.case_number,
        case_title=case.title,
        deadline=str(case.deadline),
        deadline_time=deadline_time or "",
    )


async def _notification_exists(
    db: AsyncSession,
    case_id: object,
    recipient_phone: str,
    scheduled_date: date,
    interval_type: str = "days",
    interval_value: int = 0,
) -> bool:
    """Check if a notification already exists for the same case + phone + date.

    For minute-based notifications the message body is also checked against
    the interval value to prevent duplicate notifications for the *same*
    minute interval while still allowing different minute intervals on the
    same day.
    """
    result = await db.execute(
        select(Notification)
        .where(
            and_(
                Notification.case_id == case_id,
                Notification.recipient_phone == recipient_phone,
                Notification.status.in_([
                    NotificationStatus.pending,
                    NotificationStatus.sent,
                ]),
            )
        )
    )
    notifications = list(result.scalars().all())

    if not notifications:
        return False

    for notification in notifications:
        if notification.scheduled_at.date() == scheduled_date:
            if interval_type == "days":
                return True
            # For minute-based: check the message body contains the
            # specific minute interval indicator to allow different
            # minute intervals on the same day.
            minute_indicator = f"{interval_value} dakika"
            if minute_indicator in (notification.message_body or ""):
                return True

    return False


async def create_deadline_notifications(
    db: AsyncSession,
    cases_with_deadlines: list[dict],
    system_user_id: object | None = None,
) -> list[Notification]:
    """Create WhatsApp notifications for upcoming deadlines.

    For each case:
    - If lawyer has a phone number, create notification for lawyer
    - If client has a phone number, create notification for client
    - Skip users without phone numbers
    - Skip if a notification for same case/deadline/recipient already exists
    """
    now = datetime.now(timezone.utc)
    created_notifications: list[Notification] = []

    for entry in cases_with_deadlines:
        case: Case = entry["case"]
        interval_type: str = entry.get("interval_type", "days")
        interval_value: int = entry.get("interval_value", entry.get("days_remaining", 0))
        lawyer: User | None = entry["lawyer"]
        client: User | None = entry["client"]

        # Select the correct WhatsApp template name
        if interval_type == "minutes":
            wa_template_name = MINUTE_TEMPLATE_NAMES.get(interval_value)
            templates = MINUTE_TEMPLATES.get(interval_value)
            deadline_time_str = str(case.deadline_time) if case.deadline_time else ""
        else:
            wa_template_name = DAY_TEMPLATE_NAMES.get(entry["days_remaining"])
            templates = DEADLINE_TEMPLATES.get(entry["days_remaining"])
            deadline_time_str = None

        if templates is None or wa_template_name is None:
            continue

        # Build WhatsApp template components with positional parameters
        # {{1}} = name, {{2}} = case_number, {{3}} = deadline
        deadline_display = deadline_time_str or str(case.deadline)

        # Determine the created_by user (prefer lawyer, fall back to client)
        creator_id = system_user_id
        if creator_id is None:
            if lawyer is not None:
                creator_id = lawyer.id
            elif client is not None:
                creator_id = client.id
            else:
                continue

        # Notify the lawyer
        if lawyer is not None and lawyer.phone and lawyer.is_active:
            already_exists = await _notification_exists(
                db, case.id, lawyer.phone, now.date(),
                interval_type=interval_type,
                interval_value=interval_value,
            )
            if not already_exists:
                message = _format_message(
                    templates["lawyer"], case, lawyer, client,
                    deadline_time=deadline_time_str,
                )
                components = [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": lawyer.full_name},
                            {"type": "text", "text": case.case_number},
                            {"type": "text", "text": deadline_display},
                        ],
                    }
                ]
                notification = await create_notification(
                    db,
                    created_by=creator_id,
                    recipient_phone=lawyer.phone,
                    recipient_name=lawyer.full_name,
                    message_type=NotificationType.template,
                    template_name=wa_template_name,
                    template_language="tr",
                    message_body=message,
                    scheduled_at=now,
                    case_id=case.id,
                    template_components=json.dumps(components),
                )
                created_notifications.append(notification)

        # Notify the client
        if client is not None and client.phone and client.is_active:
            already_exists = await _notification_exists(
                db, case.id, client.phone, now.date(),
                interval_type=interval_type,
                interval_value=interval_value,
            )
            if not already_exists:
                message = _format_message(
                    templates["client"], case, lawyer, client,
                    deadline_time=deadline_time_str,
                )
                components = [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": client.full_name},
                            {"type": "text", "text": case.case_number},
                            {"type": "text", "text": deadline_display},
                        ],
                    }
                ]
                notification = await create_notification(
                    db,
                    created_by=creator_id,
                    recipient_phone=client.phone,
                    recipient_name=client.full_name,
                    message_type=NotificationType.template,
                    template_name=wa_template_name,
                    template_language="tr",
                    message_body=message,
                    scheduled_at=now,
                    case_id=case.id,
                    template_components=json.dumps(components),
                )
                created_notifications.append(notification)

    return created_notifications


async def run_ip_agent(db: AsyncSession) -> dict:
    """Run the full IP Agent cycle.

    1. Scan for upcoming deadlines (day-based and minute-based)
    2. Create notifications for each
    3. Update last_run_at on the agent config
    4. Return summary
    """
    from app.agents.ip_agent.schemas import DeadlineAlert

    reminder_days = await _get_reminder_days(db)
    reminder_minutes = await _get_reminder_minutes(db)
    cases_with_deadlines = await scan_upcoming_deadlines(
        db, reminder_days=reminder_days, reminder_minutes=reminder_minutes,
    )

    notifications = await create_deadline_notifications(db, cases_with_deadlines)

    # Update last_run_at
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_name == IP_AGENT_NAME)
    )
    config = result.scalar_one_or_none()
    if config is not None:
        config.last_run_at = now
        await db.flush()

    # Build per-case notification counts
    case_notification_counts: dict[object, int] = {}
    for n in notifications:
        case_notification_counts[n.case_id] = (
            case_notification_counts.get(n.case_id, 0) + 1
        )

    alerts: list[dict] = []
    for entry in cases_with_deadlines:
        case = entry["case"]
        interval_type = entry.get("interval_type", "days")
        interval_value = entry.get("interval_value", entry.get("days_remaining", 0))
        alerts.append(
            DeadlineAlert(
                case_id=case.id,
                case_number=case.case_number,
                case_title=case.title,
                deadline=case.deadline,
                days_remaining=entry["days_remaining"],
                interval_type=interval_type,
                interval_value=interval_value,
                lawyer_name=(
                    entry["lawyer"].full_name if entry["lawyer"] else None
                ),
                client_name=(
                    entry["client"].full_name if entry["client"] else None
                ),
                notifications_created=case_notification_counts.get(case.id, 0),
            ).model_dump()
        )

    return {
        "scanned_cases": len(cases_with_deadlines),
        "deadlines_found": len(cases_with_deadlines),
        "notifications_created": len(notifications),
        "alerts": alerts,
    }

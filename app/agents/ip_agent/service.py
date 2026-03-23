"""IP Agent — Deadline tracking and auto-notification service.

Scans active cases for upcoming deadlines and creates WhatsApp
notifications for the assigned lawyer and case client.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.ip_agent.models import AgentConfig
from app.agents.ip_agent.templates import DEADLINE_TEMPLATES
from app.cases.models import Case, CaseStatus
from app.notifications.models import Notification, NotificationStatus, NotificationType
from app.notifications.service import create_notification
from app.users.models import User

logger = logging.getLogger(__name__)

IP_AGENT_NAME = "ip_agent"
DEFAULT_REMINDER_DAYS = [30, 7, 1]


async def _get_reminder_days(db: AsyncSession) -> list[int]:
    """Load configured reminder days from the database, falling back to defaults."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_name == IP_AGENT_NAME)
    )
    config = result.scalar_one_or_none()
    if config is None or not config.is_enabled:
        if config is not None and not config.is_enabled:
            return []
        return list(DEFAULT_REMINDER_DAYS)

    try:
        return [int(d.strip()) for d in config.reminder_days.split(",") if d.strip()]
    except ValueError:
        logger.warning("Invalid reminder_days in agent config, using defaults")
        return list(DEFAULT_REMINDER_DAYS)


async def scan_upcoming_deadlines(
    db: AsyncSession,
    reminder_days: list[int] | None = None,
) -> list[dict]:
    """Scan all active cases for upcoming deadlines.

    Returns list of { case, days_remaining, lawyer, client } for cases
    where deadline is exactly one of the configured reminder day intervals away.
    """
    if reminder_days is None:
        reminder_days = await _get_reminder_days(db)

    if not reminder_days:
        return []

    today = datetime.now(timezone.utc).date()

    target_dates = {days: today + timedelta(days=days) for days in reminder_days}

    result = await db.execute(
        select(Case)
        .where(
            and_(
                Case.status != CaseStatus.closed,
                Case.deadline.isnot(None),
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
            "lawyer": case.assigned_lawyer,
            "client": case.client,
        })

    return matches


def _format_message(
    template: str,
    case: Case,
    lawyer: User | None,
    client: User | None,
) -> str:
    """Format a template string with case and user data."""
    return template.format(
        lawyer_name=lawyer.full_name if lawyer else "",
        client_name=client.full_name if client else "",
        case_number=case.case_number,
        case_title=case.title,
        deadline=str(case.deadline),
    )


async def _notification_exists(
    db: AsyncSession,
    case_id: object,
    recipient_phone: str,
    scheduled_date: date,
) -> bool:
    """Check if a notification already exists for the same case + phone + date.

    Prevents duplicate notifications when the agent runs multiple times on the
    same day.
    """
    result = await db.execute(
        select(Notification.id)
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
    existing = list(result.scalars().all())

    # Check date portion of scheduled_at for each existing notification
    if not existing:
        return False

    # Re-query with full records to check date
    full_result = await db.execute(
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
    notifications = list(full_result.scalars().all())
    for notification in notifications:
        if notification.scheduled_at.date() == scheduled_date:
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
        days_remaining: int = entry["days_remaining"]
        lawyer: User | None = entry["lawyer"]
        client: User | None = entry["client"]

        templates = DEADLINE_TEMPLATES.get(days_remaining)
        if templates is None:
            continue

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
                db, case.id, lawyer.phone, now.date()
            )
            if not already_exists:
                message = _format_message(
                    templates["lawyer"], case, lawyer, client
                )
                notification = await create_notification(
                    db,
                    created_by=creator_id,
                    recipient_phone=lawyer.phone,
                    recipient_name=lawyer.full_name,
                    message_type=NotificationType.text,
                    message_body=message,
                    scheduled_at=now,
                    case_id=case.id,
                )
                created_notifications.append(notification)

        # Notify the client
        if client is not None and client.phone and client.is_active:
            already_exists = await _notification_exists(
                db, case.id, client.phone, now.date()
            )
            if not already_exists:
                message = _format_message(
                    templates["client"], case, lawyer, client
                )
                notification = await create_notification(
                    db,
                    created_by=creator_id,
                    recipient_phone=client.phone,
                    recipient_name=client.full_name,
                    message_type=NotificationType.text,
                    message_body=message,
                    scheduled_at=now,
                    case_id=case.id,
                )
                created_notifications.append(notification)

    return created_notifications


async def run_ip_agent(db: AsyncSession) -> dict:
    """Run the full IP Agent cycle.

    1. Scan for upcoming deadlines
    2. Create notifications for each
    3. Update last_run_at on the agent config
    4. Return summary
    """
    from app.agents.ip_agent.schemas import DeadlineAlert

    reminder_days = await _get_reminder_days(db)
    cases_with_deadlines = await scan_upcoming_deadlines(db, reminder_days=reminder_days)

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
        alerts.append(
            DeadlineAlert(
                case_id=case.id,
                case_number=case.case_number,
                case_title=case.title,
                deadline=case.deadline,
                days_remaining=entry["days_remaining"],
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

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction
from app.audit.service import Actor, log_audit_event
from app.notifications.models import Notification, NotificationStatus


async def create_notification(
    db: AsyncSession,
    created_by: uuid.UUID,
    **kwargs: object,
) -> Notification:
    """Create a new scheduled notification."""
    notification = Notification(created_by=created_by, **kwargs)
    db.add(notification)
    await db.flush()
    await db.refresh(notification)

    await log_audit_event(
        db,
        actor=Actor.user(created_by),
        action=AuditAction.notification_created,
        target_type="notification",
        target_id=notification.id,
        case_id=kwargs.get("case_id"),  # type: ignore[arg-type]
        details=f"Notification created: type={kwargs.get('notification_type')}",
    )

    return notification


async def get_notification(
    db: AsyncSession,
    notification_id: uuid.UUID,
) -> Notification | None:
    """Fetch a single notification by ID."""
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    return result.scalar_one_or_none()


async def list_notifications(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    status: NotificationStatus | None = None,
    case_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> tuple[list[Notification], int]:
    """List notifications with optional filters. Returns (notifications, total_count)."""
    query = select(Notification)
    count_query = select(func.count(Notification.id))

    if status is not None:
        query = query.where(Notification.status == status)
        count_query = count_query.where(Notification.status == status)

    if case_id is not None:
        query = query.where(Notification.case_id == case_id)
        count_query = count_query.where(Notification.case_id == case_id)

    if created_by is not None:
        query = query.where(Notification.created_by == created_by)
        count_query = count_query.where(Notification.created_by == created_by)

    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    result = await db.execute(
        query.offset(skip).limit(limit).order_by(Notification.created_at.desc())
    )
    notifications = list(result.scalars().all())
    return notifications, total


async def update_notification(
    db: AsyncSession,
    notification: Notification,
    *,
    actor: Actor,
    **kwargs: object,
) -> Notification:
    """Update notification fields. Only non-None values are applied.

    Writes one audit row: ``notification_cancelled`` if the update moved
    the notification to ``cancelled``, ``notification_updated`` otherwise.
    """
    old_status = notification.status
    changed = sorted(k for k, v in kwargs.items() if v is not None)
    for key, value in kwargs.items():
        if value is not None:
            setattr(notification, key, value)
    await db.flush()
    await db.refresh(notification)

    cancelled = (
        notification.status != old_status
        and notification.status == NotificationStatus.cancelled
    )
    await log_audit_event(
        db,
        actor=actor,
        action=(
            AuditAction.notification_cancelled
            if cancelled
            else AuditAction.notification_updated
        ),
        target_type="notification",
        target_id=notification.id,
        case_id=notification.case_id,
        details=f"Notification updated: fields={changed}",
    )
    return notification


async def cancel_notification(
    db: AsyncSession,
    notification: Notification,
    *,
    actor: Actor,
) -> Notification:
    """Cancel a pending notification."""
    notification.status = NotificationStatus.cancelled
    await db.flush()
    await db.refresh(notification)

    await log_audit_event(
        db,
        actor=actor,
        action=AuditAction.notification_cancelled,
        target_type="notification",
        target_id=notification.id,
        case_id=notification.case_id,
        details="Notification cancelled",
    )
    return notification


async def get_pending_notifications(
    db: AsyncSession,
    before: datetime,
) -> list[Notification]:
    """Get all pending notifications scheduled before the given time."""
    result = await db.execute(
        select(Notification)
        .where(Notification.status == NotificationStatus.pending)
        .where(Notification.scheduled_at <= before)
        .order_by(Notification.scheduled_at.asc())
    )
    return list(result.scalars().all())


async def mark_sent(
    db: AsyncSession,
    notification: Notification,
    whatsapp_message_id: str,
    *,
    actor: Actor,
) -> Notification:
    """Mark a notification as successfully sent."""
    notification.status = NotificationStatus.sent
    notification.sent_at = datetime.now(timezone.utc)
    notification.whatsapp_message_id = whatsapp_message_id
    await db.flush()
    await db.refresh(notification)

    await log_audit_event(
        db,
        actor=actor,
        action=AuditAction.notification_sent,
        target_type="notification",
        target_id=notification.id,
        case_id=notification.case_id,
        details="Notification sent",
    )
    return notification


async def mark_failed(
    db: AsyncSession,
    notification: Notification,
    error_message: str,
    *,
    actor: Actor | None = None,
) -> Notification:
    """Mark a notification as failed.

    ``actor`` is still optional here (``None`` = not audited) until every
    caller of this function has been checked; the error text is never
    copied into the audit row (it can contain the recipient's number).
    """
    notification.status = NotificationStatus.failed
    notification.error_message = error_message
    await db.flush()
    await db.refresh(notification)

    if actor is not None:
        await log_audit_event(
            db,
            actor=actor,
            action=AuditAction.notification_failed,
            target_type="notification",
            target_id=notification.id,
            case_id=notification.case_id,
            details=f"Notification failed after {notification.retry_count} attempts",
        )
    return notification

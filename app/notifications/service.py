import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    **kwargs: object,
) -> Notification:
    """Update notification fields. Only non-None values are applied."""
    for key, value in kwargs.items():
        if value is not None:
            setattr(notification, key, value)
    await db.flush()
    await db.refresh(notification)
    return notification


async def cancel_notification(
    db: AsyncSession,
    notification: Notification,
) -> Notification:
    """Cancel a pending notification."""
    notification.status = NotificationStatus.cancelled
    await db.flush()
    await db.refresh(notification)
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
) -> Notification:
    """Mark a notification as successfully sent."""
    notification.status = NotificationStatus.sent
    notification.sent_at = datetime.now(timezone.utc)
    notification.whatsapp_message_id = whatsapp_message_id
    await db.flush()
    await db.refresh(notification)
    return notification


async def mark_failed(
    db: AsyncSession,
    notification: Notification,
    error_message: str,
) -> Notification:
    """Mark a notification as failed."""
    notification.status = NotificationStatus.failed
    notification.error_message = error_message
    await db.flush()
    await db.refresh(notification)
    return notification

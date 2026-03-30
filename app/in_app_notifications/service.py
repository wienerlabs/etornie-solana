import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.in_app_notifications.models import InAppNotification, InAppNotificationType


async def create_notification(
    db: AsyncSession,
    recipient_id: uuid.UUID,
    notification_type: InAppNotificationType,
    title: str,
    message: str,
    sender_id: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
) -> InAppNotification:
    """Create an in-app notification for a user."""
    notif = InAppNotification(
        recipient_id=recipient_id,
        sender_id=sender_id,
        notification_type=notification_type,
        title=title,
        message=message,
        case_id=case_id,
    )
    db.add(notif)
    await db.flush()
    await db.refresh(notif)
    return notif


async def list_notifications(
    db: AsyncSession,
    recipient_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False,
) -> tuple[list[InAppNotification], int, int]:
    """List notifications for a user. Returns (notifications, total, unread_count)."""
    base = select(InAppNotification).where(
        InAppNotification.recipient_id == recipient_id
    )

    if unread_only:
        base = base.where(InAppNotification.is_read.is_(False))

    count_result = await db.execute(
        select(func.count(InAppNotification.id)).where(
            InAppNotification.recipient_id == recipient_id
        )
    )
    total = count_result.scalar_one()

    unread_result = await db.execute(
        select(func.count(InAppNotification.id)).where(
            and_(
                InAppNotification.recipient_id == recipient_id,
                InAppNotification.is_read.is_(False),
            )
        )
    )
    unread_count = unread_result.scalar_one()

    result = await db.execute(
        base.order_by(InAppNotification.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total, unread_count


async def mark_as_read(
    db: AsyncSession,
    notification_id: uuid.UUID,
    recipient_id: uuid.UUID,
) -> bool:
    """Mark a single notification as read. Returns True if found and updated."""
    result = await db.execute(
        update(InAppNotification)
        .where(
            and_(
                InAppNotification.id == notification_id,
                InAppNotification.recipient_id == recipient_id,
            )
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return result.rowcount > 0  # type: ignore[union-attr]


async def mark_all_as_read(
    db: AsyncSession,
    recipient_id: uuid.UUID,
) -> int:
    """Mark all unread notifications as read. Returns count of updated rows."""
    result = await db.execute(
        update(InAppNotification)
        .where(
            and_(
                InAppNotification.recipient_id == recipient_id,
                InAppNotification.is_read.is_(False),
            )
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return result.rowcount  # type: ignore[union-attr]


async def get_unread_count(
    db: AsyncSession,
    recipient_id: uuid.UUID,
) -> int:
    """Get count of unread notifications for a user."""
    result = await db.execute(
        select(func.count(InAppNotification.id)).where(
            and_(
                InAppNotification.recipient_id == recipient_id,
                InAppNotification.is_read.is_(False),
            )
        )
    )
    return result.scalar_one()


# --- Notification trigger helpers ---


async def notify_document_uploaded(
    db: AsyncSession,
    case_id: uuid.UUID,
    case_title: str,
    uploader_name: str,
    uploader_id: uuid.UUID,
    recipient_id: uuid.UUID,
    filename: str,
) -> None:
    """Notify when a document is uploaded to a case."""
    await create_notification(
        db,
        recipient_id=recipient_id,
        sender_id=uploader_id,
        notification_type=InAppNotificationType.document_uploaded,
        title="Yeni Evrak Yüklendi",
        message=f'"{case_title}" dosyasına "{filename}" yüklendi ({uploader_name}).',
        case_id=case_id,
    )


async def notify_document_reviewed(
    db: AsyncSession,
    case_id: uuid.UUID,
    case_title: str,
    reviewer_name: str,
    reviewer_id: uuid.UUID,
    recipient_id: uuid.UUID,
    filename: str,
    approved: bool,
    rejection_reason: str | None = None,
) -> None:
    """Notify when a document is approved or rejected."""
    if approved:
        ntype = InAppNotificationType.document_approved
        title = "Evrak Onaylandı"
        message = f'"{case_title}" dosyasındaki "{filename}" onaylandı ({reviewer_name}).'
    else:
        ntype = InAppNotificationType.document_rejected
        title = "Evrak Reddedildi"
        reason = f" Sebep: {rejection_reason}" if rejection_reason else ""
        message = f'"{case_title}" dosyasındaki "{filename}" reddedildi ({reviewer_name}).{reason}'

    await create_notification(
        db,
        recipient_id=recipient_id,
        sender_id=reviewer_id,
        notification_type=ntype,
        title=title,
        message=message,
        case_id=case_id,
    )


async def notify_note_added(
    db: AsyncSession,
    case_id: uuid.UUID,
    case_title: str,
    author_name: str,
    author_id: uuid.UUID,
    recipient_id: uuid.UUID,
) -> None:
    """Notify when a note is added to a case."""
    await create_notification(
        db,
        recipient_id=recipient_id,
        sender_id=author_id,
        notification_type=InAppNotificationType.note_added,
        title="Yeni Not Eklendi",
        message=f'"{case_title}" dosyasına yeni bir not eklendi ({author_name}).',
        case_id=case_id,
    )

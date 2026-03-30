import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.in_app_notifications.schemas import (
    InAppNotificationListResponse,
    InAppNotificationResponse,
)
from app.in_app_notifications.service import (
    get_unread_count,
    list_notifications,
    mark_all_as_read,
    mark_as_read,
)
from app.users.models import User

router = APIRouter(prefix="/in-app-notifications", tags=["in-app-notifications"])


@router.get("", response_model=InAppNotificationListResponse)
async def list_my_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InAppNotificationListResponse:
    """List current user's in-app notifications."""
    notifications, total, unread_count = await list_notifications(
        db,
        recipient_id=current_user.id,
        skip=skip,
        limit=limit,
        unread_only=unread_only,
    )
    return InAppNotificationListResponse(
        notifications=[
            InAppNotificationResponse.model_validate(n) for n in notifications
        ],
        total=total,
        unread_count=unread_count,
    )


@router.get("/unread-count")
async def get_my_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Get unread notification count for the current user."""
    count = await get_unread_count(db, current_user.id)
    return {"unread_count": count}


@router.patch("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_notification_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Mark a single notification as read."""
    updated = await mark_as_read(db, notification_id, current_user.id)
    return {"success": updated}


@router.patch("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Mark all notifications as read."""
    count = await mark_all_as_read(db, current_user.id)
    return {"marked_read": count}

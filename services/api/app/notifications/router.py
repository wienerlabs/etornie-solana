import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.notifications.models import NotificationStatus, NotificationType
from app.notifications.schemas import (
    NotificationCreate,
    NotificationListResponse,
    NotificationResponse,
    NotificationUpdate,
    SendNowRequest,
    SendNowResponse,
)
from app.notifications.scheduler import process_pending_notifications
from app.notifications.service import (
    cancel_notification,
    create_notification,
    get_notification,
    list_notifications,
    update_notification,
)
from app.notifications.whatsapp import WhatsAppClient, get_whatsapp_client
from app.users.models import User, UserRole

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_notification_endpoint(
    data: NotificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> NotificationResponse:
    """Create a scheduled notification (admin or lawyer only)."""
    notification = await create_notification(
        db,
        created_by=current_user.id,
        recipient_phone=data.recipient_phone,
        recipient_name=data.recipient_name,
        message_type=data.message_type,
        template_name=data.template_name,
        template_language=data.template_language,
        message_body=data.message_body,
        scheduled_at=data.scheduled_at,
        case_id=data.case_id,
        max_retries=data.max_retries,
    )
    return NotificationResponse.model_validate(notification)


@router.get("", response_model=NotificationListResponse)
async def list_notifications_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: NotificationStatus | None = Query(None, alias="status"),
    case_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    """List notifications with filters.

    Admin sees all; lawyer sees only their own.
    """
    created_by: uuid.UUID | None = None
    if current_user.role == UserRole.lawyer:
        created_by = current_user.id
    elif current_user.role == UserRole.client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    notifications, total = await list_notifications(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        case_id=case_id,
        created_by=created_by,
    )
    return NotificationListResponse(
        notifications=[NotificationResponse.model_validate(n) for n in notifications],
        total=total,
    )


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification_endpoint(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationResponse:
    """Get notification detail."""
    notification = await get_notification(db, notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    if current_user.role == UserRole.client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    if (
        current_user.role == UserRole.lawyer
        and notification.created_by != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this notification",
        )

    return NotificationResponse.model_validate(notification)


@router.patch("/{notification_id}", response_model=NotificationResponse)
async def update_notification_endpoint(
    notification_id: uuid.UUID,
    data: NotificationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> NotificationResponse:
    """Update a notification (reschedule or cancel)."""
    notification = await get_notification(db, notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    if (
        current_user.role == UserRole.lawyer
        and notification.created_by != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this notification",
        )

    if notification.status != NotificationStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending notifications can be updated",
        )

    update_data = data.model_dump(exclude_unset=True)
    notification = await update_notification(db, notification, **update_data)
    return NotificationResponse.model_validate(notification)


@router.delete("/{notification_id}", response_model=NotificationResponse)
async def delete_notification_endpoint(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> NotificationResponse:
    """Cancel a notification (soft delete — sets status to cancelled)."""
    notification = await get_notification(db, notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    if (
        current_user.role == UserRole.lawyer
        and notification.created_by != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this notification",
        )

    if notification.status != NotificationStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending notifications can be cancelled",
        )

    notification = await cancel_notification(db, notification)
    return NotificationResponse.model_validate(notification)


@router.post("/send", response_model=SendNowResponse)
async def send_now_endpoint(
    data: SendNowRequest,
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
    wa_client: WhatsAppClient = Depends(get_whatsapp_client),
) -> SendNowResponse:
    """Send a message immediately via WhatsApp API (admin or lawyer)."""
    try:
        if data.message_type == NotificationType.template:
            response = await wa_client.send_template_message(
                to=data.recipient_phone,
                template_name=data.template_name or "",
                language_code=data.template_language,
            )
        else:
            response = await wa_client.send_text_message(
                to=data.recipient_phone,
                body=data.message_body or "",
            )

        messages = response.get("messages", [])
        wa_message_id = messages[0]["id"] if messages else None

        return SendNowResponse(
            success=True,
            whatsapp_message_id=wa_message_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        return SendNowResponse(
            success=False,
            error=str(exc),
        )
    finally:
        await wa_client.close()


@router.post("/process")
async def process_notifications_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
    wa_client: WhatsAppClient = Depends(get_whatsapp_client),
) -> dict:
    """Trigger the notification scheduler manually (admin only).

    Processes all due pending notifications.
    """
    try:
        result = await process_pending_notifications(db, wa_client)
        return result
    finally:
        await wa_client.close()


@router.get("/templates/list", response_model=list[dict])
async def list_templates_endpoint(
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
    wa_client: WhatsAppClient = Depends(get_whatsapp_client),
) -> list[dict]:
    """List available WhatsApp message templates."""
    try:
        templates = await wa_client.get_templates(
            business_account_id=settings.whatsapp_business_account_id,
        )
        return templates
    finally:
        await wa_client.close()

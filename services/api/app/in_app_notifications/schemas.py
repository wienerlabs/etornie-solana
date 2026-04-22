import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.in_app_notifications.models import InAppNotificationType


class InAppNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_id: uuid.UUID
    sender_id: uuid.UUID | None
    notification_type: InAppNotificationType
    title: str
    message: str
    case_id: uuid.UUID | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class InAppNotificationListResponse(BaseModel):
    notifications: list[InAppNotificationResponse]
    total: int
    unread_count: int

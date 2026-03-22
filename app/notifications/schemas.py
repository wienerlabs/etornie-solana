import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.notifications.models import NotificationStatus, NotificationType


class NotificationCreate(BaseModel):
    recipient_phone: str = Field(min_length=1)
    recipient_name: str | None = None
    message_type: NotificationType
    template_name: str | None = None
    template_language: str = "en_US"
    message_body: str | None = None
    scheduled_at: datetime
    case_id: uuid.UUID | None = None
    max_retries: int = Field(default=3, ge=0, le=10)

    @model_validator(mode="after")
    def validate_message_fields(self) -> "NotificationCreate":
        # Strip leading '+' from phone number
        self.recipient_phone = self.recipient_phone.lstrip("+")

        if not self.recipient_phone.isdigit():
            msg = "recipient_phone must contain only digits (no spaces, dashes, or letters)"
            raise ValueError(msg)

        if self.message_type == NotificationType.template and not self.template_name:
            msg = "template_name is required for template messages"
            raise ValueError(msg)

        if self.message_type == NotificationType.text and not self.message_body:
            msg = "message_body is required for text messages"
            raise ValueError(msg)

        return self


class NotificationUpdate(BaseModel):
    scheduled_at: datetime | None = None
    status: NotificationStatus | None = None

    @model_validator(mode="after")
    def validate_status_change(self) -> "NotificationUpdate":
        if self.status is not None and self.status != NotificationStatus.cancelled:
            msg = "Only cancellation is allowed via update"
            raise ValueError(msg)
        return self


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_phone: str
    recipient_name: str | None
    message_type: NotificationType
    template_name: str | None
    template_language: str
    message_body: str | None
    status: NotificationStatus
    scheduled_at: datetime
    sent_at: datetime | None
    error_message: str | None
    retry_count: int
    max_retries: int
    whatsapp_message_id: str | None
    created_by: uuid.UUID
    case_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int


class SendNowRequest(BaseModel):
    recipient_phone: str = Field(min_length=1)
    message_type: NotificationType
    template_name: str | None = None
    template_language: str = "en_US"
    message_body: str | None = None

    @model_validator(mode="after")
    def validate_message_fields(self) -> "SendNowRequest":
        self.recipient_phone = self.recipient_phone.lstrip("+")

        if not self.recipient_phone.isdigit():
            msg = "recipient_phone must contain only digits (no spaces, dashes, or letters)"
            raise ValueError(msg)

        if self.message_type == NotificationType.template and not self.template_name:
            msg = "template_name is required for template messages"
            raise ValueError(msg)

        if self.message_type == NotificationType.text and not self.message_body:
            msg = "message_body is required for text messages"
            raise ValueError(msg)

        return self


class SendNowResponse(BaseModel):
    success: bool
    whatsapp_message_id: str | None = None
    error: str | None = None

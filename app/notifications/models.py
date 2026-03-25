import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NotificationStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"


class NotificationType(str, enum.Enum):
    template = "template"
    text = "text"


class Notification(Base):
    __tablename__ = "notifications"

    recipient_phone: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    recipient_name: Mapped[str | None] = mapped_column(String(255))
    message_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type"),
        nullable=False,
    )
    template_name: Mapped[str | None] = mapped_column(String(255))
    template_language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en_US"
    )
    template_components: Mapped[str | None] = mapped_column(Text)  # JSON string
    message_body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status"),
        nullable=False,
        default=NotificationStatus.pending,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    whatsapp_message_id: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cases.id"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    creator: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[created_by],
    )
    case: Mapped["Case | None"] = relationship(  # noqa: F821
        foreign_keys=[case_id],
    )

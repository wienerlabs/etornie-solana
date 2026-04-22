import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InAppNotificationType(str, enum.Enum):
    document_uploaded = "document_uploaded"
    document_approved = "document_approved"
    document_rejected = "document_rejected"
    note_added = "note_added"
    case_updated = "case_updated"
    case_created = "case_created"


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"

    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notification_type: Mapped[InAppNotificationType] = mapped_column(
        Enum(InAppNotificationType, name="in_app_notification_type"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    recipient: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[recipient_id],
    )
    sender: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[sender_id],
    )

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditAction(str, enum.Enum):
    note_cancelled = "note_cancelled"
    document_cancelled = "document_cancelled"
    case_created = "case_created"
    case_updated = "case_updated"
    case_status_changed = "case_status_changed"
    document_created = "document_created"
    document_updated = "document_updated"
    # Reserved: documents are only ever soft-deleted today (see
    # document_cancelled), so nothing writes this value yet.
    document_deleted = "document_deleted"
    notification_created = "notification_created"
    notification_updated = "notification_updated"
    notification_cancelled = "notification_cancelled"
    notification_sent = "notification_sent"
    notification_failed = "notification_failed"
    in_app_notification_created = "in_app_notification_created"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    # Nullable: a system-initiated mutation (job, webhook) has no user to
    # point at. ``actor_type`` says what kind of actor it was; when the
    # action ran on behalf of a known user, actor_id carries that user.
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    # "user" | "agent" | "system" | "webhook" (see app.audit.service.ActorType).
    actor_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        server_default="user",
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # No ON DELETE rule on purpose: ON DELETE SET NULL would be an UPDATE
    # on audit_logs, which the append-only trigger rejects, so deleting a
    # case that has audit rows would fail anyway. NO ACTION states that
    # outright: an audited case cannot be deleted.
    case_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("cases.id"),
        nullable=True,
    )
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    actor: Mapped[Optional["User"]] = relationship(foreign_keys=[actor_id])  # noqa: F821

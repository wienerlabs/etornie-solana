import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    uploaded = "uploaded"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class Document(Base):
    __tablename__ = "documents"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.uploaded,
    )
    document_type: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # ZK ownership-claim fields. All nullable so documents uploaded before
    # the ownership flow was introduced keep working. See migration
    # d2e3f4a5b6c7_add_document_ownership_fields.py and
    # circuits/file_ownership/ for the matching circuit + VK.
    file_hash_hex: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    ownership_commitment_hex: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    ownership_proof_pda: Mapped[str | None] = mapped_column(
        String(44), nullable=True
    )
    ownership_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    case: Mapped["Case"] = relationship(back_populates="documents")  # noqa: F821
    uploaded_by_user: Mapped["User"] = relationship(  # noqa: F821
        back_populates="documents",
        foreign_keys=[uploaded_by],
    )
    reviewer: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[reviewed_by],
    )
    cancelled_by_user: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[cancelled_by],
    )

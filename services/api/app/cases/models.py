import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CaseType(str, enum.Enum):
    trademark = "trademark"
    patent = "patent"
    design = "design"
    copyright = "copyright"


class CaseStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    under_review = "under_review"
    closed = "closed"


class Case(Base):
    __tablename__ = "cases"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    case_number: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    case_type: Mapped[CaseType] = mapped_column(
        Enum(CaseType, name="case_type"),
        nullable=False,
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status"),
        nullable=False,
        default=CaseStatus.open,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    guest_client_name: Mapped[str | None] = mapped_column(String(255))
    guest_client_email: Mapped[str | None] = mapped_column(String(255))
    guest_client_phone: Mapped[str | None] = mapped_column(String(30))
    assigned_lawyer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
    )
    jurisdiction: Mapped[str | None] = mapped_column(String(255))
    nice_classes: Mapped[str | None] = mapped_column(String(500))  # comma-separated: "25,35,41"
    filing_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    deadline_time: Mapped[time | None] = mapped_column(Time, nullable=True)
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
    attestation_tx: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attestation_pda: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_wallet: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    client: Mapped["User | None"] = relationship(  # noqa: F821
        back_populates="client_cases",
        foreign_keys=[client_id],
    )
    assigned_lawyer: Mapped["User | None"] = relationship(  # noqa: F821
        back_populates="assigned_cases",
        foreign_keys=[assigned_lawyer_id],
    )
    notes: Mapped[list["CaseNote"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="case",
        cascade="all, delete-orphan",
    )


class CaseNote(Base):
    __tablename__ = "case_notes"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    case: Mapped["Case"] = relationship(back_populates="notes")
    author: Mapped["User"] = relationship(  # noqa: F821
        back_populates="case_notes",
        foreign_keys=[author_id],
    )

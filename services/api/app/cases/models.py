import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, SmallInteger, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CaseEventType(int, enum.Enum):
    """On-chain lifecycle event codes (match the program's event_type arg)."""

    STATUS_CHANGED = 1
    DOCUMENT_UPLOADED = 2
    PROPOSAL_GENERATED = 3
    PROPOSAL_ACCEPTED = 4
    PROPOSAL_REJECTED = 5
    NOTE_ADDED = 6
    CLIENT_ACCEPTED = 10
    CLOSED = 99


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


class CaseNftState(str, enum.Enum):
    """Soul-bound Case NFT lifecycle on devnet."""

    none = "none"
    pending_claim = "pending_claim"
    minted = "minted"
    burned = "burned"


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
    nft_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nft_state: Mapped[CaseNftState] = mapped_column(
        Enum(CaseNftState, name="case_nft_state"),
        nullable=False,
        default=CaseNftState.none,
        server_default=CaseNftState.none.value,
    )
    nft_setup_tx: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nft_mint_tx: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nft_burn_tx: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nft_burned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Renewal lifecycle — EUIPO trademarks are renewable for indefinite
    # 10-year periods, so ``renewal_due_at`` is filing_date + 10 years
    # at promotion time and re-stamped each successful renewal.
    # ``last_renewed_at`` lets the dispatcher detect a recent renewal
    # and reset reminder cadences without scanning RenewalReminder
    # rows.
    renewal_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_renewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

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


class CaseEvent(Base):
    __tablename__ = "case_events"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tx_signature: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_wallet: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
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

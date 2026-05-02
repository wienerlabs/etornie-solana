"""SQLAlchemy models for the agent orchestrator layer.

Mirrors the schema introduced in migration f9a0b1c2d3e4. Existing tables
(`cases`, `users`, ...) are referenced via FK only and never modified.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.cases.models import CaseType
from app.database import Base


# JSONB on PostgreSQL, plain JSON elsewhere (e.g. SQLite for tests).
_JSONType = JSON().with_variant(JSONB, "postgresql")


# ---------------------------------------------------------------------------
# Enums (must match names in migration f9a0b1c2d3e4)
# ---------------------------------------------------------------------------


class AgentSessionStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class AgentMessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class AgentUploadStatus(str, enum.Enum):
    uploaded = "uploaded"
    validated = "validated"
    rejected = "rejected"
    cancelled = "cancelled"


class CaseDraftStatus(str, enum.Enum):
    collecting = "collecting"
    validated = "validated"
    awaiting_payment = "awaiting_payment"
    paid = "paid"
    submitted = "submitted"
    abandoned = "abandoned"


class ApplicantType(str, enum.Enum):
    individual = "individual"
    legal_entity = "legal_entity"


class FilingPlatform(str, enum.Enum):
    EUIPO = "EUIPO"
    WIPO = "WIPO"
    USPTO = "USPTO"
    UKIPO = "UKIPO"


class FilingAttemptStatus(str, enum.Enum):
    pending = "pending"
    submitted = "submitted"
    accepted = "accepted"
    rejected = "rejected"
    error = "error"
    retrying = "retrying"


class PaymentType(str, enum.Enum):
    service_fee = "service_fee"
    platform_fee = "platform_fee"


class PaymentProvider(str, enum.Enum):
    x402 = "x402"
    stripe = "stripe"
    nowpayments = "nowpayments"
    coinbase_commerce = "coinbase_commerce"
    solana_pay = "solana_pay"


class PaymentIntentStatus(str, enum.Enum):
    created = "created"
    awaiting = "awaiting"
    confirmed = "confirmed"
    failed = "failed"
    refunded = "refunded"
    expired = "expired"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AgentSession(Base):
    __tablename__ = "agent_session"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[AgentSessionStatus] = mapped_column(
        Enum(AgentSessionStatus, name="agent_session_status", create_type=False),
        nullable=False,
        default=AgentSessionStatus.active,
        server_default=AgentSessionStatus.active.value,
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AgentMessage.created_at",
    )
    draft: Mapped["CaseDraft | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index(
            "ix_agent_session_user_active",
            "user_id",
            "deleted_at",
            "last_activity_at",
        ),
    )


class AgentMessage(Base):
    __tablename__ = "agent_message"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[AgentMessageRole] = mapped_column(
        Enum(AgentMessageRole, name="agent_message_role", create_type=False),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_arguments: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    tool_result: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped["AgentSession"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_agent_message_session_time", "session_id", "created_at"),
    )


class CaseDraft(Base):
    __tablename__ = "case_draft"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_session.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_type: Mapped[CaseType] = mapped_column(
        Enum(CaseType, name="case_type", create_type=False),
        nullable=False,
    )
    mark_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    applicant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    applicant_type: Mapped[ApplicantType | None] = mapped_column(
        Enum(ApplicantType, name="applicant_type", create_type=False),
        nullable=True,
    )
    target_countries: Mapped[list] = mapped_column(_JSONType, nullable=False, default=list)
    selected_platforms: Mapped[list] = mapped_column(_JSONType, nullable=False, default=list)
    nice_classes: Mapped[list] = mapped_column(_JSONType, nullable=False, default=list)
    logo_file_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    additional_document_ids: Mapped[list] = mapped_column(
        _JSONType, nullable=False, default=list
    )
    status: Mapped[CaseDraftStatus] = mapped_column(
        Enum(CaseDraftStatus, name="case_draft_status", create_type=False),
        nullable=False,
        default=CaseDraftStatus.collecting,
        server_default=CaseDraftStatus.collecting.value,
    )
    validation_errors: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    promoted_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
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

    session: Mapped["AgentSession"] = relationship(back_populates="draft")
    filing_attempts: Mapped[list["FilingAttempt"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["PaymentIntent"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status <> 'submitted' OR promoted_case_id IS NOT NULL",
            name="ck_case_draft_submitted_has_case",
        ),
        Index("ix_case_draft_user_status", "user_id", "status"),
    )


class FilingAttempt(Base):
    __tablename__ = "filing_attempt"

    case_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_draft.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[FilingPlatform] = mapped_column(
        Enum(FilingPlatform, name="filing_platform", create_type=False),
        nullable=False,
    )
    status: Mapped[FilingAttemptStatus] = mapped_column(
        Enum(FilingAttemptStatus, name="filing_attempt_status", create_type=False),
        nullable=False,
        default=FilingAttemptStatus.pending,
        server_default=FilingAttemptStatus.pending.value,
    )
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_payload: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    draft: Mapped["CaseDraft"] = relationship(back_populates="filing_attempts")

    __table_args__ = (
        Index("ix_filing_attempt_draft_platform", "case_draft_id", "platform"),
        # Partial unique index 'uq_filing_attempt_accepted' is created in
        # the migration directly (SQLAlchemy lacks a clean DDL for partial
        # unique indexes on Postgres).
    )


class PaymentIntent(Base):
    __tablename__ = "payment_intent"

    case_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_draft.id", ondelete="CASCADE"),
        nullable=False,
    )
    payment_type: Mapped[PaymentType] = mapped_column(
        Enum(PaymentType, name="payment_type", create_type=False),
        nullable=False,
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, name="payment_provider", create_type=False),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    usd_equivalent: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    status: Mapped[PaymentIntentStatus] = mapped_column(
        Enum(PaymentIntentStatus, name="payment_intent_status", create_type=False),
        nullable=False,
        default=PaymentIntentStatus.created,
        server_default=PaymentIntentStatus.created.value,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    x402_tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gateway_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway_metadata: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    draft: Mapped["CaseDraft"] = relationship(back_populates="payments")

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_intent_idempotency_key"),
        Index(
            "ix_payment_intent_draft_type_status",
            "case_draft_id",
            "payment_type",
            "status",
        ),
    )


class AgentUpload(Base):
    """File uploaded inside an agent session.

    The file lives on disk under ``<upload_dir>/agent/<session_id>/<uuid>_<name>``.
    Vision-based validation against the expected document type runs through the
    ``validate_uploaded_document`` tool and writes its findings here. Optional
    zero-knowledge ownership claim mirrors the documents table — same circuit,
    same on-chain verifier, same PDA layout.
    """

    __tablename__ = "agent_upload"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[AgentUploadStatus] = mapped_column(
        Enum(AgentUploadStatus, name="agent_upload_status", create_type=False),
        nullable=False,
        default=AgentUploadStatus.uploaded,
        server_default=AgentUploadStatus.uploaded.value,
    )

    expected_document_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detected_document_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    validation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_details: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Mirror of documents.* ZK ownership fields. Same circuit, same on-chain
    # verifier, same commitment scheme — keeps the prove-ownership flow
    # uniform whether the file came in through cases or the agent.
    file_hash_hex: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ownership_commitment_hex: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    ownership_proof_pda: Mapped[str | None] = mapped_column(String(44), nullable=True)
    ownership_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    linked_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    linked_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    __table_args__ = (
        Index("ix_agent_upload_session_created", "session_id", "created_at"),
        Index("ix_agent_upload_user_status", "user_id", "status"),
        Index("ix_agent_upload_sha256", "sha256_hex"),
    )

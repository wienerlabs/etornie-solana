"""SQLAlchemy model for Stripe-bound compliance proofs."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ComplianceArtifactStatus(str, enum.Enum):
    """Mirrors the VARCHAR status values; Python-side convenience only."""

    created = "created"
    verified_onchain = "verified_onchain"
    failed = "failed"


class ComplianceArtifact(Base):
    """A Groth16 proof bound to a single Stripe-confirmed payment.

    One artifact per ``PaymentIntent`` — the unique constraint on
    ``payment_intent_id`` keeps the auto-submit hook idempotent across
    webhook + success_url races.
    """

    __tablename__ = "compliance_artifact"

    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_intent.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    case_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_draft.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Canonical filing-context hash (sha256 over a deterministic
    # concatenation of draft fields + platform + payment_intent_id).
    # Always 32 bytes.
    query_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    # Poseidon(secret, qh_hi, qh_lo) — 32-byte BE field element.
    commitment_be32: Mapped[bytes] = mapped_column(
        LargeBinary(32), nullable=False
    )

    # Groth16 on-chain payload (matches the format the existing zk
    # verifier program consumes; see dashboard/src/lib/zk/proofConversion.ts).
    proof_a: Mapped[bytes] = mapped_column(LargeBinary(64), nullable=False)
    proof_b: Mapped[bytes] = mapped_column(LargeBinary(128), nullable=False)
    proof_c: Mapped[bytes] = mapped_column(LargeBinary(64), nullable=False)
    journal_digest: Mapped[bytes] = mapped_column(
        LargeBinary(32), nullable=False
    )
    # JSON list of 3 base64 strings (qh_hi, qh_lo, commitment); easier
    # to round-trip than three more bytea columns and keeps the
    # circuit's public-signal order self-documenting.
    public_inputs_b64: Mapped[list] = mapped_column(JSONB, nullable=False)

    # Plain VARCHAR + CHECK constraint — avoids the Postgres ENUM
    # double-create headache. See migration for the constraint.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ComplianceArtifactStatus.created.value,
        server_default=ComplianceArtifactStatus.created.value,
    )
    # Tx signature for the verify_compliance_proof on-chain call —
    # populated by M4 once the operator broadcasts the verifier tx.
    onchain_tx: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        CheckConstraint(
            "status IN ('created', 'verified_onchain', 'failed')",
            name="ck_compliance_artifact_status",
        ),
        UniqueConstraint(
            "payment_intent_id", name="uq_compliance_artifact_payment_intent"
        ),
        Index("ix_compliance_artifact_case_draft", "case_draft_id"),
        Index("ix_compliance_artifact_status", "status"),
    )

"""Add compliance_artifact for Stripe-bound Groth16 proofs.

Status is stored as a checked VARCHAR to avoid the Postgres ENUM
double-create headache: the existing PaymentIntent/CaseDraft enums
use ``create_type=False`` and ship their CREATE TYPE statements
out-of-band, but the same trick races with SQLAlchemy's column-side
DDL on fresh installs. A constrained VARCHAR keeps the schema
identical from the application's perspective.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d9
Create Date: 2026-05-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_artifact",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "payment_intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_intent.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_draft.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "commitment_be32", sa.LargeBinary(length=32), nullable=False
        ),
        sa.Column("proof_a", sa.LargeBinary(length=64), nullable=False),
        sa.Column("proof_b", sa.LargeBinary(length=128), nullable=False),
        sa.Column("proof_c", sa.LargeBinary(length=64), nullable=False),
        sa.Column(
            "journal_digest", sa.LargeBinary(length=32), nullable=False
        ),
        sa.Column("public_inputs_b64", postgresql.JSONB, nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="created",
        ),
        sa.Column("onchain_tx", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('created', 'verified_onchain', 'failed')",
            name="ck_compliance_artifact_status",
        ),
        sa.UniqueConstraint(
            "payment_intent_id",
            name="uq_compliance_artifact_payment_intent",
        ),
    )
    op.create_index(
        "ix_compliance_artifact_case_draft",
        "compliance_artifact",
        ["case_draft_id"],
    )
    op.create_index(
        "ix_compliance_artifact_status",
        "compliance_artifact",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_artifact_status", table_name="compliance_artifact")
    op.drop_index(
        "ix_compliance_artifact_case_draft", table_name="compliance_artifact"
    )
    op.drop_table("compliance_artifact")

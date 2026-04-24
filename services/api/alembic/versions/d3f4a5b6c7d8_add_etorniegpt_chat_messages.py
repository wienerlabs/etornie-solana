"""Add etorniegpt chat_messages table with x402 payment + compliance binding.

Revision ID: d3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-24

Creates `chat_messages` so every EtornieGPT query is persisted with the
x402 micro-payment tx signature and the on-chain ZK compliance PDA that
authorizes it. All on-chain fields are nullable so future admin/preview
flows (no payment required) can still insert rows.

Columns:
    user_id           : FK users.id, the authenticated requester
    question          : user query text (raw plaintext)
    answer            : EtornieGPT response text
    model             : LLM model id used (e.g. openai/gpt-oss-20b)
    country_detected  : country name resolved from the query, if any
    language          : requested response language code
    query_hash_hex    : sha256(question), 64 hex chars
    commitment_hex    : Poseidon(secret, qh_hi, qh_lo), 64 hex chars
    payer_wallet      : base58 pubkey of the wallet that paid
    payment_tx        : base58 signature of the on-chain SOL transfer
    compliance_tx     : base58 signature of the verify_compliance_proof tx
    compliance_pda    : base58 pubkey of the ComplianceRecord PDA
    created_at        : insertion timestamp
"""

from alembic import op
import sqlalchemy as sa


revision = "d3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("country_detected", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="tr"),
        sa.Column("query_hash_hex", sa.String(length=64), nullable=True),
        sa.Column("commitment_hex", sa.String(length=64), nullable=True),
        sa.Column("payer_wallet", sa.String(length=44), nullable=True),
        sa.Column("payment_tx", sa.String(length=90), nullable=True),
        sa.Column("compliance_tx", sa.String(length=90), nullable=True),
        sa.Column("compliance_pda", sa.String(length=44), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chat_messages_payment_tx", "chat_messages", ["payment_tx"]
    )
    op.create_index(
        "ix_chat_messages_created_at", "chat_messages", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_payment_tx", table_name="chat_messages")
    op.drop_table("chat_messages")

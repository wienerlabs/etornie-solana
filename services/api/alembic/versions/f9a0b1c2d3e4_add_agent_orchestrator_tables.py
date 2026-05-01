"""add agent orchestrator tables

Creates the 5 tables that back the new chat-first EtornieGPT agent layer:
  - agent_session
  - agent_message
  - case_draft
  - filing_attempt
  - payment_intent

The existing `cases` table is left untouched. A draft promotes into `cases`
only when status='submitted', via case_draft.promoted_case_id.

Revision ID: f9a0b1c2d3e4
Revises: c2d3e4f5a6b7
Create Date: 2026-04-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Enum types (idempotent — DO blocks tolerate re-runs in dev DBs)
    # ------------------------------------------------------------------
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE agent_session_status AS ENUM ('active', 'archived'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE agent_message_role AS ENUM ('user', 'assistant', 'tool'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE case_draft_status AS ENUM ("
        "'collecting', 'validated', 'awaiting_payment', 'paid', 'submitted', 'abandoned'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE applicant_type AS ENUM ('individual', 'legal_entity'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE filing_platform AS ENUM ('EUIPO', 'WIPO', 'USPTO', 'UKIPO'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE filing_attempt_status AS ENUM ("
        "'pending', 'submitted', 'accepted', 'rejected', 'error', 'retrying'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE payment_type AS ENUM ('service_fee', 'platform_fee'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE payment_provider AS ENUM ("
        "'x402', 'stripe', 'nowpayments', 'coinbase_commerce', 'solana_pay'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE payment_intent_status AS ENUM ("
        "'created', 'awaiting', 'confirmed', 'failed', 'refunded', 'expired'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    # ------------------------------------------------------------------
    # 2. agent_session
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE agent_session (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(255),
            status agent_session_status NOT NULL DEFAULT 'active',
            model VARCHAR(100) NOT NULL,
            total_input_tokens INTEGER NOT NULL DEFAULT 0,
            total_output_tokens INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.create_index(
        "ix_agent_session_user_active",
        "agent_session",
        ["user_id", "deleted_at", "last_activity_at"],
        postgresql_using="btree",
    )

    # ------------------------------------------------------------------
    # 3. agent_message
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE agent_message (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
            role agent_message_role NOT NULL,
            content TEXT,
            tool_call_id VARCHAR(100),
            tool_name VARCHAR(100),
            tool_arguments JSONB,
            tool_result JSONB,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index(
        "ix_agent_message_session_time",
        "agent_message",
        ["session_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # 4. case_draft (1:1 with agent_session)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE case_draft (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL UNIQUE REFERENCES agent_session(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            case_type case_type NOT NULL,
            mark_text VARCHAR(500),
            applicant_name VARCHAR(255),
            applicant_type applicant_type,
            target_countries JSONB NOT NULL DEFAULT '[]'::jsonb,
            selected_platforms JSONB NOT NULL DEFAULT '[]'::jsonb,
            nice_classes JSONB NOT NULL DEFAULT '[]'::jsonb,
            logo_file_id UUID,
            additional_document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            status case_draft_status NOT NULL DEFAULT 'collecting',
            validation_errors JSONB,
            promoted_case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_case_draft_submitted_has_case
                CHECK (status <> 'submitted' OR promoted_case_id IS NOT NULL)
        )
    """)
    op.create_index("ix_case_draft_user_status", "case_draft", ["user_id", "status"])

    # ------------------------------------------------------------------
    # 5. filing_attempt
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE filing_attempt (
            id UUID PRIMARY KEY,
            case_draft_id UUID NOT NULL REFERENCES case_draft(id) ON DELETE CASCADE,
            platform filing_platform NOT NULL,
            status filing_attempt_status NOT NULL DEFAULT 'pending',
            attempt_number SMALLINT NOT NULL DEFAULT 1,
            external_reference VARCHAR(255),
            request_payload JSONB,
            response_payload JSONB,
            error_message TEXT,
            submitted_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index(
        "ix_filing_attempt_draft_platform",
        "filing_attempt",
        ["case_draft_id", "platform"],
    )
    # At most one accepted attempt per (draft, platform) — enforced via partial unique index
    op.execute("""
        CREATE UNIQUE INDEX uq_filing_attempt_accepted
        ON filing_attempt (case_draft_id, platform)
        WHERE status = 'accepted'
    """)

    # ------------------------------------------------------------------
    # 6. payment_intent
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE payment_intent (
            id UUID PRIMARY KEY,
            case_draft_id UUID NOT NULL REFERENCES case_draft(id) ON DELETE CASCADE,
            payment_type payment_type NOT NULL,
            provider payment_provider NOT NULL,
            amount NUMERIC(20, 8) NOT NULL,
            currency VARCHAR(10) NOT NULL,
            usd_equivalent NUMERIC(12, 2),
            status payment_intent_status NOT NULL DEFAULT 'created',
            idempotency_key VARCHAR(255) NOT NULL UNIQUE,
            x402_tx_hash VARCHAR(128),
            gateway_payment_id VARCHAR(255),
            gateway_metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            confirmed_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ
        )
    """)
    op.create_index(
        "ix_payment_intent_draft_type_status",
        "payment_intent",
        ["case_draft_id", "payment_type", "status"],
    )


def downgrade() -> None:
    op.drop_table("payment_intent")
    op.drop_table("filing_attempt")
    op.drop_table("case_draft")
    op.drop_table("agent_message")
    op.drop_table("agent_session")

    op.execute("DROP TYPE IF EXISTS payment_intent_status")
    op.execute("DROP TYPE IF EXISTS payment_provider")
    op.execute("DROP TYPE IF EXISTS payment_type")
    op.execute("DROP TYPE IF EXISTS filing_attempt_status")
    op.execute("DROP TYPE IF EXISTS filing_platform")
    op.execute("DROP TYPE IF EXISTS applicant_type")
    op.execute("DROP TYPE IF EXISTS case_draft_status")
    op.execute("DROP TYPE IF EXISTS agent_message_role")
    op.execute("DROP TYPE IF EXISTS agent_session_status")

"""add agent_upload table

Stores files attached inline to an agent session (the new EtornieGPT
chat surface). Mirrors the ZK ownership-claim columns from
``documents`` so the same on-chain verifier and proof flow works
without branching.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-05-02 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE agent_upload_status AS ENUM ("
        "'uploaded', 'validated', 'rejected', 'cancelled'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE agent_upload (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            original_filename VARCHAR(500) NOT NULL,
            stored_path VARCHAR(1000) NOT NULL,
            mime_type VARCHAR(200),
            size_bytes BIGINT NOT NULL,
            sha256_hex VARCHAR(64) NOT NULL,
            status agent_upload_status NOT NULL DEFAULT 'uploaded',
            expected_document_type VARCHAR(200),
            detected_document_type VARCHAR(200),
            validation_summary TEXT,
            validation_details JSONB,
            validated_at TIMESTAMPTZ,
            file_hash_hex VARCHAR(64),
            ownership_commitment_hex VARCHAR(64),
            ownership_proof_pda VARCHAR(44),
            ownership_verified_at TIMESTAMPTZ,
            linked_case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
            linked_document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
            cancelled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index(
        "ix_agent_upload_session_created",
        "agent_upload",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_agent_upload_user_status",
        "agent_upload",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_agent_upload_sha256",
        "agent_upload",
        ["sha256_hex"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_upload_sha256", table_name="agent_upload")
    op.drop_index("ix_agent_upload_user_status", table_name="agent_upload")
    op.drop_index("ix_agent_upload_session_created", table_name="agent_upload")
    op.drop_table("agent_upload")
    op.execute("DROP TYPE IF EXISTS agent_upload_status")

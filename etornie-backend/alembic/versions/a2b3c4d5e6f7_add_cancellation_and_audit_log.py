"""add cancellation fields and audit_logs table

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add 'cancelled' to document_status enum
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'cancelled'")

    # 2. Add cancellation fields to documents
    op.add_column("documents", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("cancelled_by", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_documents_cancelled_by_users", "documents", "users", ["cancelled_by"], ["id"])

    # 3. Add cancellation fields to case_notes
    op.add_column("case_notes", sa.Column("is_cancelled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("case_notes", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("case_notes", sa.Column("cancelled_by", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_case_notes_cancelled_by_users", "case_notes", "users", ["cancelled_by"], ["id"])

    # 4. Create audit_action enum and audit_logs table
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE audit_action AS ENUM ('note_cancelled', 'document_cancelled'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE audit_logs (
            id UUID PRIMARY KEY,
            actor_id UUID NOT NULL REFERENCES users(id),
            action audit_action NOT NULL,
            target_type VARCHAR(50) NOT NULL,
            target_id UUID NOT NULL,
            case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
            details TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_target_id", "audit_logs", ["target_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.execute("DROP TYPE IF EXISTS audit_action")

    op.drop_constraint("fk_case_notes_cancelled_by_users", "case_notes", type_="foreignkey")
    op.drop_column("case_notes", "cancelled_by")
    op.drop_column("case_notes", "cancelled_at")
    op.drop_column("case_notes", "is_cancelled")

    op.drop_constraint("fk_documents_cancelled_by_users", "documents", type_="foreignkey")
    op.drop_column("documents", "cancelled_by")
    op.drop_column("documents", "cancelled_at")

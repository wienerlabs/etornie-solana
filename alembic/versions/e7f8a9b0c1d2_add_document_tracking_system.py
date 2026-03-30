"""add document tracking system

Revision ID: e7f8a9b0c1d2
Revises: b7e8f9a0c1d2
Create Date: 2026-03-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "b7e8f9a0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Reusable enum reference (never auto-creates)
document_status_enum = sa.Enum(
    "pending", "uploaded", "approved", "rejected",
    name="document_status",
    create_type=False,
)


def upgrade() -> None:
    # 1. Create enum type
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE document_status AS ENUM ('pending', 'uploaded', 'approved', 'rejected'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    # 2. Add new columns to documents table
    op.add_column("documents", sa.Column("status", document_status_enum, nullable=False, server_default="uploaded"))
    op.add_column("documents", sa.Column("document_type", sa.String(500), nullable=True))
    op.add_column("documents", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.create_foreign_key("fk_documents_reviewed_by_users", "documents", "users", ["reviewed_by"], ["id"])

    # 3. Create required_document_templates table
    op.execute("""
        CREATE TABLE required_document_templates (
            id UUID PRIMARY KEY,
            jurisdiction VARCHAR(10) NOT NULL,
            case_type VARCHAR(50),
            document_name VARCHAR(500) NOT NULL,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index("ix_required_document_templates_jurisdiction", "required_document_templates", ["jurisdiction"])

    # 4. Create case_required_documents table
    op.execute("""
        CREATE TABLE case_required_documents (
            id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            document_name VARCHAR(500) NOT NULL,
            status document_status NOT NULL DEFAULT 'pending',
            document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index("ix_case_required_documents_case_id", "case_required_documents", ["case_id"])


def downgrade() -> None:
    op.drop_table("case_required_documents")
    op.drop_table("required_document_templates")

    op.drop_constraint("fk_documents_reviewed_by_users", "documents", type_="foreignkey")
    op.drop_column("documents", "rejection_reason")
    op.drop_column("documents", "reviewed_at")
    op.drop_column("documents", "reviewed_by")
    op.drop_column("documents", "document_type")
    op.drop_column("documents", "status")

    op.execute("DROP TYPE IF EXISTS document_status")

"""add proposals table and nice_classes to cases

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nice_classes to cases
    op.add_column("cases", sa.Column("nice_classes", sa.String(500), nullable=True))

    # 2. Create proposal_status enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE proposal_status AS ENUM ('draft', 'sent', 'accepted', 'rejected'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    # 3. Create proposals table
    op.execute("""
        CREATE TABLE proposals (
            id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            country_name VARCHAR(500) NOT NULL,
            country_code VARCHAR(10),
            nice_classes VARCHAR(500) NOT NULL,
            required_documents TEXT,
            registration_period VARCHAR(255),
            protection_period VARCHAR(255),
            madrid_system VARCHAR(50),
            national_application VARCHAR(50),
            opposition_period VARCHAR(255),
            special_notes TEXT,
            price NUMERIC(12, 2),
            currency VARCHAR(10),
            status proposal_status NOT NULL DEFAULT 'draft',
            created_by UUID NOT NULL REFERENCES users(id),
            sent_at TIMESTAMPTZ,
            responded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index("ix_proposals_case_id", "proposals", ["case_id"])


def downgrade() -> None:
    op.drop_table("proposals")
    op.execute("DROP TYPE IF EXISTS proposal_status")
    op.drop_column("cases", "nice_classes")

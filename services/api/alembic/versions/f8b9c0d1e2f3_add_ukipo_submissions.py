"""Add ukipo_submissions table for UK IPO trade mark filing robot.

Revision ID: f8b9c0d1e2f3
Revises: e4f5a6b7c8d9
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f8b9c0d1e2f3"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE ukipo_mark_type AS ENUM ('word', 'figurative', 'combined', 'unusual'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE ukipo_owner_entity_type AS ENUM ("
        "'Registered Company or LLP', 'Individual(s)', 'Partnership', 'Trust', 'Other'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE ukipo_submission_status AS ENUM ("
        "'pending', 'running', 'awaiting_payment', 'filed', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE ukipo_submissions (
            id UUID PRIMARY KEY,
            case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            owner_company_name VARCHAR(500) NOT NULL,
            owner_country VARCHAR(100) NOT NULL,
            owner_address_line1 VARCHAR(500) NOT NULL,
            owner_address_line2 VARCHAR(500),
            owner_city VARCHAR(255) NOT NULL,
            owner_postcode VARCHAR(50),
            owner_email VARCHAR(255),
            owner_phone VARCHAR(50),
            owner_entity_type ukipo_owner_entity_type NOT NULL,
            owner_company_registration_number VARCHAR(50),
            mark_type ukipo_mark_type NOT NULL,
            mark_text VARCHAR(1000),
            mark_image_path VARCHAR(1000),
            nice_classes_json TEXT NOT NULL,
            status ukipo_submission_status NOT NULL DEFAULT 'pending',
            current_step VARCHAR(100),
            error_step VARCHAR(100),
            error_message TEXT,
            ipo_reference VARCHAR(100),
            ipo_application_url VARCHAR(2000),
            screenshot_path VARCHAR(1000),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index(
        "ix_ukipo_submissions_case_id",
        "ukipo_submissions",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_table("ukipo_submissions")
    op.execute("DROP TYPE IF EXISTS ukipo_submission_status")
    op.execute("DROP TYPE IF EXISTS ukipo_owner_entity_type")
    op.execute("DROP TYPE IF EXISTS ukipo_mark_type")

"""add signature_requests table (e-signature, issue #63)

Tracks documents sent to a signer through an external e-signature
provider (Yousign). Links the source PDF, the signer, the provider's
correlation ids, and the resulting signed PDF document.

Revision ID: 914ad2096e71
Revises: d4a5b6c7e8f9
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "914ad2096e71"
down_revision = "d4a5b6c7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    signature_provider = sa.Enum("yousign", name="signature_provider")
    signature_status = sa.Enum(
        "draft",
        "ongoing",
        "signed",
        "declined",
        "expired",
        "cancelled",
        "error",
        name="signature_request_status",
    )

    op.create_table(
        "signature_requests",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("signed_document_id", sa.Uuid(), nullable=True),
        sa.Column("signer_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider",
            signature_provider,
            nullable=False,
            server_default="yousign",
        ),
        sa.Column(
            "status",
            signature_status,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("provider_document_id", sa.String(length=128), nullable=True),
        sa.Column("provider_signer_id", sa.String(length=128), nullable=True),
        sa.Column("signer_email", sa.String(length=255), nullable=False),
        sa.Column("signer_name", sa.String(length=255), nullable=False),
        sa.Column("signing_url", sa.String(length=1000), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["signed_document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["signer_user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_signature_requests_case_id", "signature_requests", ["case_id"]
    )
    op.create_index(
        "ix_signature_requests_provider_request_id",
        "signature_requests",
        ["provider_request_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_signature_requests_provider_request_id",
        table_name="signature_requests",
    )
    op.drop_index(
        "ix_signature_requests_case_id", table_name="signature_requests"
    )
    op.drop_table("signature_requests")
    sa.Enum(name="signature_request_status").drop(op.get_bind())
    sa.Enum(name="signature_provider").drop(op.get_bind())

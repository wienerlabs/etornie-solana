"""Add document ZK ownership fields.

Revision ID: d2e3f4a5b6c7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-23

Adds four nullable columns to `documents` so an uploaded file can carry a
zero-knowledge ownership claim derived client-side from the file bytes and
the user's wallet signature. All columns stay nullable so existing rows
keep working without a backfill:

    file_hash_hex            -- sha256(file), 32 bytes encoded as 64 hex chars
    ownership_commitment_hex -- Poseidon(secret, fh_hi, fh_lo), 32 B hex
    ownership_proof_pda      -- FileOwnershipRecord PDA (base58 pubkey)
    ownership_verified_at    -- confirmation timestamp of the verify_file_ownership_proof tx

See programs/etornie-zk-verifier/src/lib.rs for the matching on-chain
instruction (`verify_file_ownership_proof`) and the circuit in
circuits/file_ownership/file_ownership.circom.
"""

from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("file_hash_hex", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "ownership_commitment_hex", sa.String(length=64), nullable=True
        ),
    )
    op.add_column(
        "documents",
        sa.Column("ownership_proof_pda", sa.String(length=44), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "ownership_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "ownership_verified_at")
    op.drop_column("documents", "ownership_proof_pda")
    op.drop_column("documents", "ownership_commitment_hex")
    op.drop_column("documents", "file_hash_hex")

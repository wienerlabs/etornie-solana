"""Add multi-tenancy foundation: organizations + memberships + invites.

- ``organizations`` carries the org row (slug, name, plan, settings).
- ``organization_membership`` joins users to orgs with a per-org role
  (owner / admin / member). Independent of UserRole on the user row.
- ``organization_invite`` lets an owner/admin invite by email; a token
  is generated server-side and consumed on accept.
- ``users.default_organization_id`` is the org /auth/me echoes back so
  a new login lands somewhere sensible.

Backfill: a single ``etornie-default`` org is created and EVERY
existing user becomes a member of it (role=member, owners promoted
to role=owner for admins on the user record). That preserves the
single-tenant behaviour the codebase had before the migration.

Revision ID: e5f6a7b8c9d0
Revises: c1d2e3f4a5b7
Create Date: 2026-05-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "c1d2e3f4a5b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "plan",
            sa.Enum(
                "solo",
                "team",
                "enterprise",
                name="organization_plan",
            ),
            nullable=False,
            server_default="solo",
        ),
        sa.Column("settings", sa.JSON(), nullable=True),
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
            nullable=False,
        ),
    )

    # organization_membership
    op.create_table(
        "organization_membership",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "admin",
                "member",
                name="organization_membership_role",
            ),
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_membership_org_user",
        ),
    )

    # organization_invite
    op.create_table(
        "organization_invite",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "admin",
                "member",
                name="organization_membership_role",
                create_type=False,
            ),
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "token",
            sa.String(128),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "invited_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "accepted_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # users.default_organization_id
    op.add_column(
        "users",
        sa.Column(
            "default_organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Backfill: create a default org + memberships for every existing
    # user so the runtime tenant-scoping helpers always find a row.
    # The default org is identified by a fixed slug so a re-run of the
    # migration on a partial database does not produce duplicates.
    op.execute(
        """
        INSERT INTO organizations (id, slug, name, plan, created_at, updated_at)
        SELECT gen_random_uuid(), 'etornie-default', 'Etornie (default)',
               'solo'::organization_plan, NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM organizations WHERE slug = 'etornie-default'
        );
        """
    )

    # PG enum types are strict — explicit cast keeps the CASE
    # expression typed as ``organization_membership_role`` instead of
    # the inferred ``text``.
    op.execute(
        """
        INSERT INTO organization_membership (
            id, organization_id, user_id, role, created_at
        )
        SELECT
            gen_random_uuid(),
            (SELECT id FROM organizations WHERE slug = 'etornie-default'),
            u.id,
            (CASE
                WHEN u.role::text = 'admin' THEN 'owner'
                ELSE 'member'
            END)::organization_membership_role,
            NOW()
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1
            FROM organization_membership m
            WHERE m.user_id = u.id
              AND m.organization_id = (
                  SELECT id FROM organizations WHERE slug = 'etornie-default'
              )
        );
        """
    )

    op.execute(
        """
        UPDATE users
        SET default_organization_id = (
            SELECT id FROM organizations WHERE slug = 'etornie-default'
        )
        WHERE default_organization_id IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_column("users", "default_organization_id")
    op.drop_table("organization_invite")
    op.drop_table("organization_membership")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS organization_membership_role")
    op.execute("DROP TYPE IF EXISTS organization_plan")

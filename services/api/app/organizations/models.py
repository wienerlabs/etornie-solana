"""Organization, OrganizationMembership, OrganizationInvite models.

The multi-tenant model is intentionally simple at this stage:
- Organization owns a slug + name + plan (enum for future billing tiers).
- OrganizationMembership joins users to organizations with a role
  (owner, admin, member) that is INDEPENDENT of UserRole on the user
  record (UserRole=admin is the system-level operator; the membership
  role scopes permissions inside one organization).
- OrganizationInvite carries an opaque token a prospective member
  redeems via POST /organizations/invites/{token}/accept. The token
  is hex, single-use, expires after 7 days.

Why no global org_id on users? Users can belong to multiple orgs
(via memberships) and the frontend stores a "current org" preference
in localStorage. The user record itself only carries
``default_organization_id`` so a new login lands somewhere sensible.
"""
from __future__ import annotations

import enum
import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


_JSONType: Any = JSON().with_variant(JSONB, "postgresql")


class OrganizationPlan(str, enum.Enum):
    """Billing tier. ``solo`` is the default for any org spun up by a
    self-service signup; the rest are populated when an operator
    upgrades the row manually."""

    solo = "solo"
    team = "team"
    enterprise = "enterprise"


class OrganizationMembershipRole(str, enum.Enum):
    """Per-organization role.

    Separate from UserRole — a user can be an ``owner`` of one
    organization, a ``member`` of another, and still hold
    UserRole.admin (system operator) at the global level.
    """

    owner = "owner"
    admin = "admin"
    member = "member"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[OrganizationPlan] = mapped_column(
        Enum(OrganizationPlan, name="organization_plan"),
        nullable=False,
        default=OrganizationPlan.solo,
        server_default=OrganizationPlan.solo.value,
    )
    settings: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    invites: Mapped[list["OrganizationInvite"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class OrganizationMembership(Base):
    __tablename__ = "organization_membership"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[OrganizationMembershipRole] = mapped_column(
        Enum(
            OrganizationMembershipRole,
            name="organization_membership_role",
        ),
        nullable=False,
        default=OrganizationMembershipRole.member,
        server_default=OrganizationMembershipRole.member.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        back_populates="memberships"
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_membership_org_user",
        ),
    )


def _generate_invite_token() -> str:
    """32-byte URL-safe token; collision-resistant and short enough
    to embed in an email link without truncation."""
    return secrets.token_urlsafe(32)


class OrganizationInvite(Base):
    __tablename__ = "organization_invite"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[OrganizationMembershipRole] = mapped_column(
        Enum(
            OrganizationMembershipRole,
            name="organization_membership_role",
            create_type=False,
        ),
        nullable=False,
        default=OrganizationMembershipRole.member,
        server_default=OrganizationMembershipRole.member.value,
    )
    token: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        default=_generate_invite_token,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        back_populates="invites"
    )

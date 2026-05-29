"""Organization request/response shapes."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrganizationRow(_Base):
    id: uuid.UUID
    slug: str
    name: str
    plan: str
    created_at: datetime


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        description=(
            "Optional URL-safe slug. Auto-derived from name when "
            "omitted; must be unique."
        ),
    )

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalised = value.strip().lower()
        if not normalised:
            return None
        # Same character set the slug auto-derivation produces; we
        # reject anything else at the schema layer so the user sees a
        # 422 with a useful message instead of a 500 from the DB
        # unique constraint.
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
        if any(c not in allowed for c in normalised):
            raise ValueError(
                "Slug must contain only lowercase letters, digits, "
                "and hyphens."
            )
        return normalised


class OrganizationMemberRow(_Base):
    user_id: uuid.UUID
    email: str | None
    full_name: str
    role: str
    joined_at: datetime


class OrganizationDetail(OrganizationRow):
    members: list[OrganizationMemberRow]


class OrganizationInviteCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(
        default="member",
        pattern="^(owner|admin|member)$",
    )


class OrganizationInviteRow(_Base):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    invited_by_user_id: uuid.UUID | None
    created_at: datetime


class OrganizationInviteCreateResponse(OrganizationInviteRow):
    # Token is ONLY returned at creation time so the inviter can copy
    # the invite URL; subsequent list endpoints never echo it back.
    token: str


class OrganizationInviteAcceptResponse(BaseModel):
    organization_id: uuid.UUID
    role: str

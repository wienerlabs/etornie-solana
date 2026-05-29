"""Organizations API surface — create, list mine, members, invites.

Authorisation rules:
- Any authenticated user may create a new organization (becomes the
  ``owner``).
- ``GET /organizations/me`` lists the orgs the caller belongs to,
  plus their role in each.
- ``GET /organizations/{id}`` returns details + member list when the
  caller is a member of that org (any role) or a global system admin.
- ``POST /organizations/{id}/invites`` requires the caller to be
  ``owner`` or ``admin`` of the target org.
- ``POST /organizations/invites/{token}/accept`` is open to any
  authenticated user — the token IS the authorization signal.
- ``POST /organizations/me/switch/{id}`` re-stamps the caller's
  ``default_organization_id`` so the next /auth/me lands them on the
  picked org.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.organizations.models import (
    Organization,
    OrganizationInvite,
    OrganizationMembership,
    OrganizationMembershipRole,
)
from app.organizations.schemas import (
    OrganizationCreateRequest,
    OrganizationDetail,
    OrganizationInviteAcceptResponse,
    OrganizationInviteCreateRequest,
    OrganizationInviteCreateResponse,
    OrganizationInviteRow,
    OrganizationMemberRow,
    OrganizationRow,
)
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/organizations", tags=["organizations"])


_SLUG_TRIM_RE = re.compile(r"[^a-z0-9-]+")
_DASH_COLLAPSE_RE = re.compile(r"-+")

# Invite TTL — bumping this requires no DB change; ``expires_at`` is
# stamped at create time per row.
INVITE_TTL = timedelta(days=7)


def _slugify(value: str) -> str:
    """Reduce a free-text name to the slug character set.

    Lowercase, replace non-[a-z0-9] with hyphens, collapse runs.
    Empty input -> "org" so the unique-constraint retry loop has
    SOMETHING to suffix.
    """
    lowered = value.strip().lower()
    cleaned = _SLUG_TRIM_RE.sub("-", lowered)
    collapsed = _DASH_COLLAPSE_RE.sub("-", cleaned).strip("-")
    return collapsed or "org"


async def _resolve_unique_slug(
    db: AsyncSession, *, preferred: str
) -> str:
    """Find a free slug close to ``preferred``.

    Tries the candidate as-is, then appends ``-2``, ``-3``, … until
    no organization claims it. Caps at 99 to avoid an unbounded
    loop when the DB is in a pathological state.
    """
    candidate = preferred
    for suffix in range(2, 100):
        exists = (
            await db.execute(
                select(Organization).where(Organization.slug == candidate)
            )
        ).scalar_one_or_none()
        if exists is None:
            return candidate
        candidate = f"{preferred}-{suffix}"
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "Could not derive a unique slug; please supply one explicitly.",
    )


async def _membership_or_403(
    db: AsyncSession, *, org_id: uuid.UUID, user: User
) -> OrganizationMembership:
    """Return the caller's membership in the org, or raise 403."""
    membership = (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None and user.role != UserRole.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You are not a member of this organization.",
        )
    if membership is None:
        # System admin without a membership — synthesise an
        # owner-equivalent so the route body can use the same shape.
        return OrganizationMembership(
            organization_id=org_id,
            user_id=user.id,
            role=OrganizationMembershipRole.owner,
        )
    return membership


def _is_org_admin(membership: OrganizationMembership) -> bool:
    return membership.role in (
        OrganizationMembershipRole.owner,
        OrganizationMembershipRole.admin,
    )


# ---------------------------------------------------------------------------
# Create / list
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=OrganizationRow,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: OrganizationCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationRow:
    """Create a new organization owned by the calling user.

    The caller becomes ``owner`` and (if they currently have no
    default org) the new org is stamped as their default.
    """
    preferred = (
        body.slug if body.slug else _slugify(body.name)
    )
    slug = await _resolve_unique_slug(db, preferred=preferred)

    org = Organization(slug=slug, name=body.name.strip())
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationMembershipRole.owner,
        )
    )
    if user.default_organization_id is None:
        user.default_organization_id = org.id
    await db.commit()
    await db.refresh(org)
    return OrganizationRow.model_validate(org)


@router.get("/me", response_model=list[OrganizationRow])
async def my_organizations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OrganizationRow]:
    """Orgs the calling user is a member of (any role)."""
    rows = (
        await db.execute(
            select(Organization)
            .join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Organization.id,
            )
            .where(OrganizationMembership.user_id == user.id)
            .order_by(Organization.created_at.asc())
        )
    ).scalars().all()
    return [OrganizationRow.model_validate(o) for o in rows]


@router.get("/{org_id}", response_model=OrganizationDetail)
async def organization_detail(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationDetail:
    org = (
        await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "organization not found"
        )
    await _membership_or_403(db, org_id=org_id, user=user)

    members = (
        await db.execute(
            select(OrganizationMembership, User)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(OrganizationMembership.organization_id == org_id)
            .order_by(OrganizationMembership.created_at.asc())
        )
    ).all()
    member_rows = [
        OrganizationMemberRow(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=m.role.value,
            joined_at=m.created_at,
        )
        for m, u in members
    ]
    return OrganizationDetail(
        id=org.id,
        slug=org.slug,
        name=org.name,
        plan=org.plan.value,
        created_at=org.created_at,
        members=member_rows,
    )


@router.post(
    "/me/switch/{org_id}",
    response_model=OrganizationRow,
)
async def switch_default_organization(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationRow:
    """Update the caller's default_organization_id.

    Used by the org switcher in the dashboard header; the value is
    echoed back on the next /auth/me as ``current_organization``.
    """
    await _membership_or_403(db, org_id=org_id, user=user)
    org = (
        await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "organization not found"
        )
    user.default_organization_id = org_id
    await db.commit()
    return OrganizationRow.model_validate(org)


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


@router.post(
    "/{org_id}/invites",
    response_model=OrganizationInviteCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    org_id: uuid.UUID,
    body: OrganizationInviteCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationInviteCreateResponse:
    """Create an organization invite.

    The caller must be ``owner`` or ``admin`` of the target org.
    Token is returned exactly once — subsequent list endpoints never
    echo it back so a leaked invite list does not become a leaked
    join key.
    """
    membership = await _membership_or_403(db, org_id=org_id, user=user)
    if not _is_org_admin(membership):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only org owners and admins can invite members.",
        )
    role = OrganizationMembershipRole(body.role)
    invite = OrganizationInvite(
        organization_id=org_id,
        email=body.email.strip().lower(),
        role=role,
        invited_by_user_id=user.id,
        expires_at=datetime.now(tz=timezone.utc) + INVITE_TTL,
    )
    db.add(invite)
    try:
        await db.commit()
    except IntegrityError as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Could not create invite (token collision — please retry).",
        ) from exc
    await db.refresh(invite)
    return OrganizationInviteCreateResponse(
        id=invite.id,
        organization_id=invite.organization_id,
        email=invite.email,
        role=invite.role.value,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        revoked_at=invite.revoked_at,
        invited_by_user_id=invite.invited_by_user_id,
        created_at=invite.created_at,
        token=invite.token,
    )


@router.get(
    "/{org_id}/invites",
    response_model=list[OrganizationInviteRow],
)
async def list_invites(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OrganizationInviteRow]:
    """Pending + historical invites for the org.

    Restricted to org owner/admin — same as create. Token never
    leaves the database; reset by deleting and recreating.
    """
    membership = await _membership_or_403(db, org_id=org_id, user=user)
    if not _is_org_admin(membership):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only org owners and admins can view invites.",
        )
    rows = (
        await db.execute(
            select(OrganizationInvite)
            .where(OrganizationInvite.organization_id == org_id)
            .order_by(OrganizationInvite.created_at.desc())
        )
    ).scalars().all()
    return [
        OrganizationInviteRow(
            id=r.id,
            organization_id=r.organization_id,
            email=r.email,
            role=r.role.value,
            expires_at=r.expires_at,
            accepted_at=r.accepted_at,
            revoked_at=r.revoked_at,
            invited_by_user_id=r.invited_by_user_id,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post(
    "/invites/{token}/accept",
    response_model=OrganizationInviteAcceptResponse,
)
async def accept_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationInviteAcceptResponse:
    """Redeem an invite token.

    Authentication is required (the joining user is already
    onboarded). We do NOT require the user's email to match the
    invite — that mismatch is a UX concern handled in the frontend.
    """
    invite = (
        await db.execute(
            select(OrganizationInvite).where(
                OrganizationInvite.token == token
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Invite not found"
        )
    if invite.revoked_at is not None:
        raise HTTPException(
            status.HTTP_410_GONE, "Invite has been revoked."
        )
    if invite.accepted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Invite already used."
        )
    now = datetime.now(tz=timezone.utc)
    # SQLite (test backend) stores tz-naive datetimes; normalise to
    # UTC for the comparison so the same code path works in tests
    # and against Postgres.
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(
            status.HTTP_410_GONE, "Invite has expired."
        )

    # Refuse if the user is already a member — avoids upgrading
    # someone's role silently via a stale invite.
    existing = (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id
                == invite.organization_id,
                OrganizationMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are already a member of this organization.",
        )

    db.add(
        OrganizationMembership(
            organization_id=invite.organization_id,
            user_id=user.id,
            role=invite.role,
        )
    )
    invite.accepted_at = now
    invite.accepted_by_user_id = user.id
    if user.default_organization_id is None:
        user.default_organization_id = invite.organization_id
    await db.commit()

    return OrganizationInviteAcceptResponse(
        organization_id=invite.organization_id,
        role=invite.role.value,
    )


@router.delete(
    "/{org_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invite(
    org_id: uuid.UUID,
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    membership = await _membership_or_403(db, org_id=org_id, user=user)
    if not _is_org_admin(membership):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only org owners and admins can revoke invites.",
        )
    invite = (
        await db.execute(
            select(OrganizationInvite).where(
                OrganizationInvite.id == invite_id,
                OrganizationInvite.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Invite not found"
        )
    if invite.accepted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot revoke an already-accepted invite.",
        )
    invite.revoked_at = datetime.now(tz=timezone.utc)
    await db.commit()

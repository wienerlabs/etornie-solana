"""Multi-tenancy organization tests.

Cover:
- create -> caller becomes owner, default_org stamped when null
- slug auto-derive + uniqueness retry (-2, -3, ...)
- /organizations/me lists only the caller's orgs
- detail endpoint requires membership (or system admin)
- invite flow: create + accept + revoke + already-member rejection
- switch endpoint re-stamps default_organization_id
- non-admin org members cannot invite or revoke
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import hash_password
from app.organizations.models import (
    Organization,
    OrganizationInvite,
    OrganizationMembership,
    OrganizationMembershipRole,
)
from app.users.models import User, UserRole
from tests.conftest import auth_headers


@pytest.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email="invitee@etornie.ch",
        hashed_password=hash_password("InvitePass123!"),
        full_name="Invitee",
        role=UserRole.client,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Create / list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_organization_makes_caller_owner(
    client: AsyncClient,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    res = await client.post(
        "/organizations",
        json={"name": "Acme Co"},
        headers=auth_headers(client_user),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["slug"] == "acme-co"
    org_id = uuid.UUID(body["id"])

    # Membership row exists with role=owner.
    membership = (
        await db_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.user_id == client_user.id,
            )
        )
    ).scalar_one_or_none()
    assert membership is not None
    assert membership.role == OrganizationMembershipRole.owner

    # default_organization_id stamped because the user had none.
    await db_session.refresh(client_user)
    assert client_user.default_organization_id == org_id


@pytest.mark.integration
async def test_create_organization_resolves_slug_collision(
    client: AsyncClient,
    client_user: User,
) -> None:
    first = await client.post(
        "/organizations",
        json={"name": "Acme Co"},
        headers=auth_headers(client_user),
    )
    second = await client.post(
        "/organizations",
        json={"name": "Acme Co"},
        headers=auth_headers(client_user),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["slug"] == "acme-co"
    assert second.json()["slug"] == "acme-co-2"


@pytest.mark.integration
async def test_create_rejects_invalid_slug(
    client: AsyncClient, client_user: User
) -> None:
    res = await client.post(
        "/organizations",
        json={"name": "Acme", "slug": "WITH SPACES!"},
        headers=auth_headers(client_user),
    )
    assert res.status_code == 422


@pytest.mark.integration
async def test_my_organizations_lists_only_callers_orgs(
    client: AsyncClient,
    client_user: User,
    other_user: User,
) -> None:
    await client.post(
        "/organizations",
        json={"name": "Mine"},
        headers=auth_headers(client_user),
    )
    await client.post(
        "/organizations",
        json={"name": "Theirs"},
        headers=auth_headers(other_user),
    )
    res = await client.get(
        "/organizations/me", headers=auth_headers(client_user)
    )
    names = {row["name"] for row in res.json()}
    assert "Mine" in names
    assert "Theirs" not in names


@pytest.mark.integration
async def test_detail_403_for_non_member(
    client: AsyncClient,
    client_user: User,
    other_user: User,
) -> None:
    created = await client.post(
        "/organizations",
        json={"name": "Mine"},
        headers=auth_headers(client_user),
    )
    org_id = created.json()["id"]
    res = await client.get(
        f"/organizations/{org_id}",
        headers=auth_headers(other_user),
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Switch default
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_switch_default_organization(
    client: AsyncClient,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    first = (
        await client.post(
            "/organizations",
            json={"name": "First"},
            headers=auth_headers(client_user),
        )
    ).json()
    second = (
        await client.post(
            "/organizations",
            json={"name": "Second"},
            headers=auth_headers(client_user),
        )
    ).json()
    # First becomes default at creation; switch to the second.
    res = await client.post(
        f"/organizations/me/switch/{second['id']}",
        headers=auth_headers(client_user),
    )
    assert res.status_code == 200
    await db_session.refresh(client_user)
    assert str(client_user.default_organization_id) == second["id"]


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_invite_creation_and_accept(
    client: AsyncClient,
    client_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    org = (
        await client.post(
            "/organizations",
            json={"name": "InviteOrg"},
            headers=auth_headers(client_user),
        )
    ).json()
    org_id = org["id"]

    inv = await client.post(
        f"/organizations/{org_id}/invites",
        json={"email": "invitee@etornie.ch", "role": "member"},
        headers=auth_headers(client_user),
    )
    assert inv.status_code == 201
    token = inv.json()["token"]
    assert isinstance(token, str) and len(token) > 20

    accept = await client.post(
        f"/organizations/invites/{token}/accept",
        headers=auth_headers(other_user),
    )
    assert accept.status_code == 200
    body = accept.json()
    assert body["organization_id"] == org_id
    assert body["role"] == "member"

    # Membership now exists.
    member = (
        await db_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == uuid.UUID(org_id),
                OrganizationMembership.user_id == other_user.id,
            )
        )
    ).scalar_one_or_none()
    assert member is not None
    assert member.role == OrganizationMembershipRole.member


@pytest.mark.integration
async def test_invite_accept_rejects_used_token(
    client: AsyncClient,
    client_user: User,
    other_user: User,
) -> None:
    org = (
        await client.post(
            "/organizations",
            json={"name": "OnceOrg"},
            headers=auth_headers(client_user),
        )
    ).json()
    org_id = org["id"]
    token = (
        await client.post(
            f"/organizations/{org_id}/invites",
            json={"email": "invitee@etornie.ch"},
            headers=auth_headers(client_user),
        )
    ).json()["token"]
    first = await client.post(
        f"/organizations/invites/{token}/accept",
        headers=auth_headers(other_user),
    )
    assert first.status_code == 200
    second = await client.post(
        f"/organizations/invites/{token}/accept",
        headers=auth_headers(other_user),
    )
    assert second.status_code in (409, 410)


@pytest.mark.integration
async def test_invite_accept_404_unknown_token(
    client: AsyncClient, other_user: User
) -> None:
    res = await client.post(
        "/organizations/invites/totally-fake-token/accept",
        headers=auth_headers(other_user),
    )
    assert res.status_code == 404


@pytest.mark.integration
async def test_invite_creation_forbidden_for_member(
    client: AsyncClient,
    client_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    # client_user creates the org, other_user joins as member.
    org = (
        await client.post(
            "/organizations",
            json={"name": "MemberOnly"},
            headers=auth_headers(client_user),
        )
    ).json()
    org_id = org["id"]
    inv = (
        await client.post(
            f"/organizations/{org_id}/invites",
            json={"email": "invitee@etornie.ch", "role": "member"},
            headers=auth_headers(client_user),
        )
    ).json()
    await client.post(
        f"/organizations/invites/{inv['token']}/accept",
        headers=auth_headers(other_user),
    )
    # other_user is now a member; trying to invite must 403.
    res = await client.post(
        f"/organizations/{org_id}/invites",
        json={"email": "third@etornie.ch"},
        headers=auth_headers(other_user),
    )
    assert res.status_code == 403


@pytest.mark.integration
async def test_revoke_invite(
    client: AsyncClient,
    client_user: User,
    other_user: User,
) -> None:
    org = (
        await client.post(
            "/organizations",
            json={"name": "RevokeOrg"},
            headers=auth_headers(client_user),
        )
    ).json()
    org_id = org["id"]
    inv = (
        await client.post(
            f"/organizations/{org_id}/invites",
            json={"email": "invitee@etornie.ch"},
            headers=auth_headers(client_user),
        )
    ).json()
    res = await client.delete(
        f"/organizations/{org_id}/invites/{inv['id']}",
        headers=auth_headers(client_user),
    )
    assert res.status_code == 204
    # Accept now fails — revoked.
    accept = await client.post(
        f"/organizations/invites/{inv['token']}/accept",
        headers=auth_headers(other_user),
    )
    assert accept.status_code == 410

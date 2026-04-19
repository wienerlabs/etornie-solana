"""Integration tests for lawyer verification.

Covers both email and wallet sign-up paths, plus the admin-only verify
and reject endpoints. All signatures are real ed25519 produced by pynacl;
no mocks.
"""

from __future__ import annotations

import base58
import nacl.signing
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import AuthMethod, User, UserRole


def _keypair() -> tuple[nacl.signing.SigningKey, str]:
    sk = nacl.signing.SigningKey.generate()
    return sk, base58.b58encode(bytes(sk.verify_key)).decode("ascii")


def _sign(sk: nacl.signing.SigningKey, message: str) -> str:
    return base58.b58encode(sk.sign(message.encode("utf-8")).signature).decode("ascii")


@pytest.fixture(autouse=True)
def _reset_wallet_redis():
    import app.auth.wallet_service as ws

    ws._redis = None
    yield
    ws._redis = None


async def _wallet_signin(
    client: AsyncClient,
    sk: nacl.signing.SigningKey,
    wallet: str,
    **extra,
) -> dict:
    n = (
        await client.post("/auth/wallet/nonce", json={"wallet_address": wallet})
    ).json()
    body = {
        "wallet_address": wallet,
        "message": n["message"],
        "signature": _sign(sk, n["message"]),
    }
    body.update(extra)
    res = await client.post("/auth/wallet/verify", json=body)
    return {"status": res.status_code, "body": res.json()}


# ---------------------------------------------------------------- email flow

async def test_email_client_register_is_verified_true(client: AsyncClient):
    res = await client.post(
        "/auth/register",
        json={
            "email": "v-client@etornie.ch",
            "password": "ClientPass123!",
            "full_name": "V Client",
            "role": "client",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["is_verified"] is True


async def test_email_lawyer_register_stays_pending(client: AsyncClient):
    res = await client.post(
        "/auth/register",
        json={
            "email": "v-lawyer@etornie.ch",
            "password": "LawyerPass123!",
            "full_name": "V Lawyer",
            "role": "lawyer",
            "bar_association": "Istanbul Barosu",
            "bar_number": "IST-12345",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["role"] == "lawyer"
    assert body["is_verified"] is False
    assert body["bar_association"] == "Istanbul Barosu"
    assert body["bar_number"] == "IST-12345"


async def test_email_client_does_not_persist_bar_fields(client: AsyncClient):
    """Client role should not keep bar fields even if sent."""
    res = await client.post(
        "/auth/register",
        json={
            "email": "v-client2@etornie.ch",
            "password": "ClientPass123!",
            "full_name": "V Client 2",
            "role": "client",
            "bar_association": "Istanbul Barosu",
            "bar_number": "IST-55555",
        },
    )
    body = res.json()
    assert body["role"] == "client"
    assert body["bar_association"] is None
    assert body["bar_number"] is None


# ---------------------------------------------------------------- wallet flow

async def test_wallet_client_signin_is_verified_true(client: AsyncClient):
    sk, wallet = _keypair()
    r = await _wallet_signin(client, sk, wallet)
    assert r["status"] == 200, r["body"]
    assert r["body"]["user"]["is_verified"] is True
    assert r["body"]["user"]["role"] == "client"


async def test_wallet_lawyer_signup_stays_pending_with_bar_fields(
    client: AsyncClient,
):
    sk, wallet = _keypair()
    r = await _wallet_signin(
        client,
        sk,
        wallet,
        role="lawyer",
        bar_association="California State Bar",
        bar_number="CA-987654",
        full_name="Real Lawyer",
    )
    assert r["status"] == 200, r["body"]
    user = r["body"]["user"]
    assert user["role"] == "lawyer"
    assert user["is_verified"] is False
    assert user["bar_association"] == "California State Bar"
    assert user["bar_number"] == "CA-987654"
    assert user["auth_method"] == "wallet"


async def test_wallet_admin_role_is_rejected(client: AsyncClient):
    """Wallet sign-up must not be able to self-assign the admin role."""
    sk, wallet = _keypair()
    # Request a nonce first so the verify call reaches the service layer.
    n = (
        await client.post("/auth/wallet/nonce", json={"wallet_address": wallet})
    ).json()
    res = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet,
            "message": n["message"],
            "signature": _sign(sk, n["message"]),
            "role": "admin",  # not an accepted value at the schema layer
        },
    )
    # pydantic rejects admin via the Literal["client","lawyer"] guard
    assert res.status_code == 422


async def test_wallet_existing_user_ignores_role_hint(
    client: AsyncClient, db_session: AsyncSession
):
    """A returning wallet must not be able to escalate by passing role=lawyer."""
    sk, wallet = _keypair()

    r1 = await _wallet_signin(client, sk, wallet)
    assert r1["status"] == 200
    assert r1["body"]["user"]["role"] == "client"

    r2 = await _wallet_signin(
        client,
        sk,
        wallet,
        role="lawyer",
        bar_association="Hack Bar",
        bar_number="HACK-1",
    )
    assert r2["status"] == 200
    assert r2["body"]["user"]["id"] == r1["body"]["user"]["id"]
    assert r2["body"]["user"]["role"] == "client"  # unchanged
    assert r2["body"]["user"]["bar_association"] is None
    assert r2["body"]["user"]["is_verified"] is True

    # DB record untouched
    row = (
        await db_session.execute(select(User).where(User.wallet_address == wallet))
    ).scalar_one()
    assert row.role == UserRole.client
    assert row.bar_association is None


# ---------------------------------------------------------------- admin actions

async def test_admin_verify_flips_pending_lawyer(
    client: AsyncClient, admin_user: User, db_session: AsyncSession
):
    from app.auth.utils import create_access_token

    # Self-register a pending lawyer via email
    reg = await client.post(
        "/auth/register",
        json={
            "email": "pending-lawyer@etornie.ch",
            "password": "LawPass123!",
            "full_name": "Pending Lawyer",
            "role": "lawyer",
            "bar_association": "State Bar",
            "bar_number": "SB-1",
        },
    )
    lawyer_id = reg.json()["id"]
    assert reg.json()["is_verified"] is False

    admin_token = create_access_token(str(admin_user.id), admin_user.role.value)

    res = await client.post(
        f"/users/{lawyer_id}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_verified"] is True

    # Second call is idempotent
    res2 = await client.post(
        f"/users/{lawyer_id}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res2.status_code == 200
    assert res2.json()["is_verified"] is True


async def test_admin_reject_flips_verified_to_false(
    client: AsyncClient, admin_user: User
):
    from app.auth.utils import create_access_token

    reg = await client.post(
        "/auth/register",
        json={
            "email": "reject-lawyer@etornie.ch",
            "password": "LawPass123!",
            "full_name": "Reject Lawyer",
            "role": "lawyer",
            "bar_association": "State Bar",
            "bar_number": "SB-2",
        },
    )
    lawyer_id = reg.json()["id"]

    admin_token = create_access_token(str(admin_user.id), admin_user.role.value)

    # First verify
    verify_res = await client.post(
        f"/users/{lawyer_id}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert verify_res.json()["is_verified"] is True

    # Then reject
    reject_res = await client.post(
        f"/users/{lawyer_id}/reject",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["is_verified"] is False


async def test_non_admin_cannot_verify(
    client: AsyncClient, lawyer_user: User, admin_user: User
):
    from app.auth.utils import create_access_token

    lawyer_token = create_access_token(str(lawyer_user.id), lawyer_user.role.value)

    res = await client.post(
        f"/users/{admin_user.id}/verify",
        headers={"Authorization": f"Bearer {lawyer_token}"},
    )
    assert res.status_code == 403


async def test_pending_filter_returns_only_unverified_lawyers(
    client: AsyncClient, admin_user: User, db_session: AsyncSession
):
    from app.auth.utils import create_access_token
    from app.auth.utils import hash_password

    # Seed: one pending lawyer, one verified lawyer, one client
    pending = User(
        email="pending@etornie.ch",
        hashed_password=hash_password("x" * 10),
        full_name="Pending",
        role=UserRole.lawyer,
        is_verified=False,
        bar_association="A",
        bar_number="1",
    )
    verified = User(
        email="verified@etornie.ch",
        hashed_password=hash_password("x" * 10),
        full_name="Verified",
        role=UserRole.lawyer,
        is_verified=True,
        bar_association="B",
        bar_number="2",
    )
    some_client = User(
        email="plain-client@etornie.ch",
        hashed_password=hash_password("x" * 10),
        full_name="Plain",
        role=UserRole.client,
        is_verified=True,
    )
    for u in (pending, verified, some_client):
        db_session.add(u)
    await db_session.flush()
    await db_session.commit()

    admin_token = create_access_token(str(admin_user.id), admin_user.role.value)

    res = await client.get(
        "/users?verification_status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    emails = [u["email"] for u in body["users"]]
    assert "pending@etornie.ch" in emails
    assert "verified@etornie.ch" not in emails
    assert "plain-client@etornie.ch" not in emails

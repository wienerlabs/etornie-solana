"""Integration tests for Solana wallet authentication.

All tests exercise real ed25519 cryptography generated in-process with
pynacl. No mocks, no stubs. The FastAPI app is driven through httpx's
ASGI transport.
"""

from __future__ import annotations

import asyncio
import base64
import json

import base58
import nacl.signing
import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import decode_token
from app.config import settings
from app.users.models import AuthMethod, User, UserRole


def _keypair() -> tuple[nacl.signing.SigningKey, nacl.signing.VerifyKey, str]:
    """Produce a fresh ed25519 keypair and its base58 pubkey representation."""
    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key
    pubkey_bytes = bytes(verify_key)
    wallet_address = base58.b58encode(pubkey_bytes).decode("ascii")
    return signing_key, verify_key, wallet_address


def _sign(signing_key: nacl.signing.SigningKey, message: str) -> str:
    sig = signing_key.sign(message.encode("utf-8")).signature
    return base58.b58encode(sig).decode("ascii")


@pytest.fixture(autouse=True)
def _reset_wallet_redis():
    """Reset the module-level redis client used by wallet_service."""
    import app.auth.wallet_service as ws

    ws._redis = None
    yield
    ws._redis = None


async def test_nonce_then_verify_creates_new_wallet_user(
    client: AsyncClient, db_session: AsyncSession
):
    signing_key, _vk, wallet = _keypair()

    nonce_res = await client.post("/auth/wallet/nonce", json={"wallet_address": wallet})
    assert nonce_res.status_code == 200, nonce_res.text
    nonce_data = nonce_res.json()
    assert nonce_data["wallet_address"] == wallet
    assert len(nonce_data["nonce"]) >= 32
    assert wallet in nonce_data["message"]
    assert nonce_data["nonce"] in nonce_data["message"]

    signature = _sign(signing_key, nonce_data["message"])

    verify_res = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet,
            "message": nonce_data["message"],
            "signature": signature,
        },
    )
    assert verify_res.status_code == 200, verify_res.text
    body = verify_res.json()

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]

    user_payload = body["user"]
    assert user_payload["wallet_address"] == wallet
    assert user_payload["public_handle"].startswith("etornie_")
    assert len(user_payload["public_handle"]) >= len("etornie_") + 8
    assert user_payload["auth_method"] == AuthMethod.wallet.value
    assert user_payload["role"] == UserRole.client.value
    assert user_payload["email"] is None
    assert user_payload["is_active"] is True

    # Access token decodes and carries the user's UUID + role
    decoded = decode_token(body["access_token"])
    assert decoded["sub"] == user_payload["id"]
    assert decoded["role"] == UserRole.client.value
    assert decoded["type"] == "access"

    # Persisted in the database
    result = await db_session.execute(select(User).where(User.wallet_address == wallet))
    row = result.scalar_one()
    assert row.public_handle == user_payload["public_handle"]
    assert row.email is None
    assert row.hashed_password is None
    assert row.auth_method == AuthMethod.wallet.value


async def test_second_login_reuses_same_user(client: AsyncClient, db_session: AsyncSession):
    signing_key, _vk, wallet = _keypair()

    async def _login() -> dict:
        n = (await client.post("/auth/wallet/nonce", json={"wallet_address": wallet})).json()
        v = await client.post(
            "/auth/wallet/verify",
            json={
                "wallet_address": wallet,
                "message": n["message"],
                "signature": _sign(signing_key, n["message"]),
            },
        )
        assert v.status_code == 200, v.text
        return v.json()

    first = await _login()
    second = await _login()

    assert first["user"]["id"] == second["user"]["id"]
    assert first["user"]["public_handle"] == second["user"]["public_handle"]

    result = await db_session.execute(select(User).where(User.wallet_address == wallet))
    assert len(result.scalars().all()) == 1


async def test_replay_same_nonce_is_rejected(client: AsyncClient):
    signing_key, _vk, wallet = _keypair()

    n = (await client.post("/auth/wallet/nonce", json={"wallet_address": wallet})).json()
    signature = _sign(signing_key, n["message"])

    first = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet,
            "message": n["message"],
            "signature": signature,
        },
    )
    assert first.status_code == 200

    replay = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet,
            "message": n["message"],
            "signature": signature,
        },
    )
    assert replay.status_code == 401
    assert "Nonce" in replay.json()["detail"] or "nonce" in replay.json()["detail"].lower()


async def test_tampered_message_is_rejected(client: AsyncClient):
    signing_key, _vk, wallet = _keypair()

    n = (await client.post("/auth/wallet/nonce", json={"wallet_address": wallet})).json()
    tampered = n["message"] + "\ntampered-line"
    signature = _sign(signing_key, tampered)

    res = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet,
            "message": tampered,
            "signature": signature,
        },
    )
    assert res.status_code == 401


async def test_wrong_keypair_signature_is_rejected(client: AsyncClient):
    # The verifier must refuse a signature produced by an unrelated key.
    _sk_a, _vk_a, wallet_a = _keypair()
    sk_b, _vk_b, _wallet_b = _keypair()

    n = (await client.post("/auth/wallet/nonce", json={"wallet_address": wallet_a})).json()
    bad_sig = _sign(sk_b, n["message"])

    res = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet_a,
            "message": n["message"],
            "signature": bad_sig,
        },
    )
    assert res.status_code == 401


async def test_invalid_wallet_address_rejected(client: AsyncClient):
    res = await client.post(
        "/auth/wallet/nonce",
        json={"wallet_address": "notbase58_____"},
    )
    assert res.status_code in (400, 422)


async def test_nonce_expiry_rejects_verify(
    client: AsyncClient, monkeypatch
):
    """Manually drop the cached nonce to simulate expiry, then attempt verify."""
    import app.auth.wallet_service as ws

    signing_key, _vk, wallet = _keypair()

    n = (await client.post("/auth/wallet/nonce", json={"wallet_address": wallet})).json()

    # Force-expire by deleting the Redis key.
    r = ws._get_redis()
    r.delete(f"{ws._KEY_PREFIX}{wallet}")

    res = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet,
            "message": n["message"],
            "signature": _sign(signing_key, n["message"]),
        },
    )
    assert res.status_code == 401


async def test_handle_collision_suffix(
    client: AsyncClient, db_session: AsyncSession
):
    """Two wallets with the same first 8 base58 chars must receive distinct handles.

    We can't easily force two different pubkeys to share the first 8 base58
    bytes, but we can simulate the collision branch by pre-inserting a user
    whose public_handle equals the deterministic candidate for a fresh wallet.
    The service should then fall back to the counter suffix.
    """
    _sk, _vk, wallet = _keypair()
    deterministic = f"etornie_{wallet[:8]}"

    pre = User(
        email="collide@etornie.ch",
        hashed_password="x" * 40,
        full_name="Collider",
        role=UserRole.client,
        public_handle=deterministic,
        auth_method=AuthMethod.email.value,
    )
    db_session.add(pre)
    await db_session.flush()
    await db_session.commit()

    sk_new, _vk_new, wallet_new = _keypair()
    # Force the first 8 chars of the new wallet to collide with deterministic
    # via an assertion: if the base58 encoding of a fresh random keypair
    # happens to collide, we skip. But since the deterministic candidate is
    # *based on this wallet's* prefix, we actually need the pre-existing row
    # to block the new wallet's deterministic slot. Re-do with the new wallet.
    deterministic_new = f"etornie_{wallet_new[:8]}"
    if deterministic_new != deterministic:
        # adjust pre-existing row to block the new wallet's slot instead
        pre.public_handle = deterministic_new
        await db_session.flush()
        await db_session.commit()

    n = (
        await client.post("/auth/wallet/nonce", json={"wallet_address": wallet_new})
    ).json()
    v = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet_new,
            "message": n["message"],
            "signature": _sign(sk_new, n["message"]),
        },
    )
    assert v.status_code == 200, v.text
    assigned = v.json()["user"]["public_handle"]
    assert assigned != deterministic_new
    assert assigned.startswith(deterministic_new + "_")

"""Tests for the public partner Q&A API (app/public_api).

Auth, admin key lifecycle, and rate limiting are exercised without the LLM.
The one test that actually answers a question hits the real Together AI
backend and is skipped unless TOGETHER_API_KEY is configured (no mocks).
"""

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.config import settings
from app.public_api.models import ApiKey
from app.public_api.security import enforce_rate_limit, hash_api_key
from app.users.models import User
from tests.conftest import auth_headers

pytestmark = pytest.mark.integration


async def _mint_key(client: AsyncClient, admin: User, **body) -> dict:
    payload = {"label": "partner-platform", **body}
    res = await client.post(
        "/admin/api-keys", json=payload, headers=auth_headers(admin)
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_chat_without_api_key_is_401(client: AsyncClient):
    res = await client.post("/api/v1/chat", json={"question": "merhaba"})
    assert res.status_code == 401


async def test_chat_with_unknown_api_key_is_401(client: AsyncClient):
    res = await client.post(
        "/api/v1/chat",
        json={"question": "merhaba"},
        headers={"X-API-Key": "etk_does_not_exist"},
    )
    assert res.status_code == 401


async def test_non_admin_cannot_mint_key(
    client: AsyncClient, client_user: User
):
    res = await client.post(
        "/admin/api-keys",
        json={"label": "x"},
        headers=auth_headers(client_user),
    )
    assert res.status_code == 403


async def test_admin_mint_list_revoke_lifecycle(
    client: AsyncClient, admin_user: User, db_session
):
    # Mint
    created = await _mint_key(client, admin_user)
    raw_key = created["api_key"]
    assert raw_key.startswith("etk_")
    assert created["rate_limit_per_minute"] == 60

    # Only the hash is stored, never the plaintext.
    stored = await db_session.get(ApiKey, uuid.UUID(created["id"]))
    assert stored is not None
    assert stored.key_hash == hash_api_key(raw_key)
    assert raw_key not in (stored.key_hash,)

    # List shows it (no plaintext / no hash in the schema)
    listed = await client.get("/admin/api-keys", headers=auth_headers(admin_user))
    assert listed.status_code == 200
    ids = [k["id"] for k in listed.json()]
    assert created["id"] in ids
    assert all("api_key" not in k and "key_hash" not in k for k in listed.json())

    # Revoke
    revoked = await client.delete(
        f"/admin/api-keys/{created['id']}", headers=auth_headers(admin_user)
    )
    assert revoked.status_code == 204

    # The revoked key no longer authenticates (rejected before any LLM call).
    res = await client.post(
        "/api/v1/chat",
        json={"question": "merhaba"},
        headers={"X-API-Key": raw_key},
    )
    assert res.status_code == 401


async def test_revoke_unknown_key_is_404(
    client: AsyncClient, admin_user: User
):
    res = await client.delete(
        f"/admin/api-keys/{uuid.uuid4()}", headers=auth_headers(admin_user)
    )
    assert res.status_code == 404


def test_rate_limit_enforced_against_real_redis():
    # A real (unpersisted) key with a tiny limit; real Redis counter.
    key = ApiKey(
        id=uuid.uuid4(),
        key_hash="unit-test",
        label="rl",
        is_active=True,
        rate_limit_per_minute=2,
    )
    enforce_rate_limit(key)  # 1
    enforce_rate_limit(key)  # 2
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(key)  # 3 -> over limit
    assert exc.value.status_code == 429


def test_rate_limit_zero_means_unlimited():
    key = ApiKey(
        id=uuid.uuid4(),
        key_hash="unit-test-0",
        label="rl0",
        is_active=True,
        rate_limit_per_minute=0,
    )
    for _ in range(50):
        enforce_rate_limit(key)  # never raises


@pytest.mark.skipif(
    not settings.together_api_key,
    reason="TOGETHER_API_KEY not configured — skips the real LLM call",
)
async def test_chat_returns_answer_with_valid_key(
    client: AsyncClient, admin_user: User
):
    created = await _mint_key(client, admin_user)
    res = await client.post(
        "/api/v1/chat",
        json={"question": "What is a trademark?", "language": "en"},
        headers={"X-API-Key": created["api_key"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["answer"], str) and body["answer"]
    assert "model" in body

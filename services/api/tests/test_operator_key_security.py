"""Operator key security tests — encryption-at-rest + audit log."""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.models import OperatorKeyAccessLog
from app.security.operator_key import (
    OperatorKeyError,
    decrypt_if_needed,
    encrypt_plaintext,
)
from app.users.models import User
from tests.conftest import auth_headers


# ---------------------------------------------------------------------------
# Pure functions: decrypt_if_needed / encrypt_plaintext
# ---------------------------------------------------------------------------


def test_decrypt_if_needed_passes_through_plaintext() -> None:
    payload = "[12, 34, 56, 78]"
    assert decrypt_if_needed(payload) == payload


def test_round_trip_encrypted_payload(monkeypatch) -> None:
    master = Fernet.generate_key().decode()
    monkeypatch.setenv("OPERATOR_KEY_MASTER_KEY", master)
    payload = "[12, 34, 56, 78]"
    blob = encrypt_plaintext(payload)
    assert blob.startswith("etornie-key-v1:")
    assert decrypt_if_needed(blob) == payload


def test_decrypt_fails_without_master_key(monkeypatch) -> None:
    monkeypatch.delenv("OPERATOR_KEY_MASTER_KEY", raising=False)
    blob = "etornie-key-v1:gAAAAA"
    with pytest.raises(OperatorKeyError):
        decrypt_if_needed(blob)


def test_decrypt_fails_with_wrong_master_key(monkeypatch) -> None:
    right = Fernet.generate_key().decode()
    wrong = Fernet.generate_key().decode()
    monkeypatch.setenv("OPERATOR_KEY_MASTER_KEY", right)
    blob = encrypt_plaintext("[1, 2, 3]")
    monkeypatch.setenv("OPERATOR_KEY_MASTER_KEY", wrong)
    with pytest.raises(OperatorKeyError):
        decrypt_if_needed(blob)


# ---------------------------------------------------------------------------
# DB-backed log + admin endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_audit_log_endpoint_returns_persisted_rows(
    client: AsyncClient,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            OperatorKeyAccessLog(
                caller_context="test.sign",
                op_kind="sign",
                success=True,
            ),
            OperatorKeyAccessLog(
                caller_context="test.verify_bad",
                op_kind="verify",
                success=False,
                note="invalid signature",
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/admin/operator-keys/audit",
        headers=auth_headers(admin_user),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 2
    contexts = {r["caller_context"] for r in body["items"]}
    assert "test.sign" in contexts
    assert "test.verify_bad" in contexts


@pytest.mark.integration
async def test_audit_log_filter_by_op_kind(
    client: AsyncClient,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            OperatorKeyAccessLog(
                caller_context="f.a", op_kind="sign", success=True
            ),
            OperatorKeyAccessLog(
                caller_context="f.b", op_kind="verify", success=True
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/admin/operator-keys/audit?op_kind=verify",
        headers=auth_headers(admin_user),
    )
    items = res.json()["items"]
    assert all(r["op_kind"] == "verify" for r in items)


@pytest.mark.integration
async def test_audit_log_filter_by_success(
    client: AsyncClient,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            OperatorKeyAccessLog(
                caller_context="ok.a", op_kind="sign", success=True
            ),
            OperatorKeyAccessLog(
                caller_context="bad.a", op_kind="sign", success=False
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/admin/operator-keys/audit?success=false",
        headers=auth_headers(admin_user),
    )
    items = res.json()["items"]
    assert all(r["success"] is False for r in items)


@pytest.mark.integration
async def test_audit_log_forbidden_for_client(
    client: AsyncClient, client_user: User
) -> None:
    res = await client.get(
        "/admin/operator-keys/audit",
        headers=auth_headers(client_user),
    )
    assert res.status_code == 403


@pytest.mark.integration
async def test_audit_log_unauthorised(client: AsyncClient) -> None:
    res = await client.get("/admin/operator-keys/audit")
    assert res.status_code == 401

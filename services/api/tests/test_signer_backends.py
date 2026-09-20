"""Unit tests for the operator signer backend switch (issue #21 review fixes).

Pure unit tests — no real Vault, no real DB. httpx.AsyncClient is
monkeypatched with an in-memory fake, and log_operator_access is
monkeypatched to a recorder rather than exercising the real audit DB
path (log_operator_access opens its own DB session independent of this
suite's `db_session` fixture, so asserting a persisted row here would
couple this unit test to unrelated DB wiring — capturing the call
arguments is what these tests actually care about).
"""
from __future__ import annotations

import base64

import pytest
from solders.pubkey import Pubkey

from app.config import settings
from app.security import signer_backends
from app.security.signer_backends import (
    VaultOperatorSigner,
    VaultSignerError,
    _fetch_vault_pubkey,
    load_vault_operator,
)
from app.solana.client import SolanaClientError, _load_operator

pytestmark = pytest.mark.unit


def _make_fake_async_client(*, get_response=None, post_response=None):
    """Build a class standing in for httpx.AsyncClient's async-with usage."""

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *exc_info) -> bool:
            return False

        async def get(self, url, headers=None):
            assert get_response is not None, "test forgot to configure get_response"
            return get_response

        async def post(self, url, json=None, headers=None):
            assert post_response is not None, "test forgot to configure post_response"
            return post_response

    return _FakeClient


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self) -> dict:
        return self._json_data


@pytest.fixture(autouse=True)
def _reset_signer_state(monkeypatch):
    """Every test starts from a clean, known-good baseline."""
    monkeypatch.setattr(signer_backends, "_cached_pubkey", None)
    monkeypatch.setattr(settings, "signer_backend", "file")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "vault_addr", "")
    monkeypatch.setattr(settings, "vault_token", "")
    monkeypatch.setattr(settings, "vault_transit_key_name", "etornie-operator")


@pytest.fixture
def fake_log_calls(monkeypatch):
    """Capture log_operator_access calls instead of hitting the real DB."""
    calls: list[dict] = []

    def _fake(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(signer_backends, "log_operator_access", _fake)
    return calls


# ---------------------------------------------------------------------------
# Backend switch
# ---------------------------------------------------------------------------


async def test_unknown_signer_backend_raises(monkeypatch):
    monkeypatch.setattr(settings, "signer_backend", "totally-not-a-backend")
    with pytest.raises(SolanaClientError, match="unknown SIGNER_BACKEND"):
        await _load_operator()


# ---------------------------------------------------------------------------
# Production gate (the ENVIRONMENT / ETORNIE_ENV blocker)
# ---------------------------------------------------------------------------


async def test_file_backend_blocked_in_production(monkeypatch):
    monkeypatch.setattr(settings, "signer_backend", "file")
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(
        SolanaClientError, match="disabled when ENVIRONMENT=production"
    ):
        await _load_operator()


async def test_production_gate_does_not_fire_outside_production(monkeypatch):
    """The gate must be specific to 'production', not fail-closed everywhere."""
    monkeypatch.setattr(settings, "signer_backend", "file")
    monkeypatch.setattr(settings, "environment", "staging")
    try:
        await _load_operator()
    except SolanaClientError as exc:
        assert "ENVIRONMENT=production" not in str(exc)


# ---------------------------------------------------------------------------
# Vault error wrapping — also covers missing-config -> VaultSignerError ->
# re-raised as SolanaClientError at the _load_operator call site.
# ---------------------------------------------------------------------------


async def test_vault_backend_missing_config_raises_solana_client_error(
    monkeypatch,
):
    monkeypatch.setattr(settings, "signer_backend", "vault")
    monkeypatch.setattr(settings, "vault_addr", "")
    monkeypatch.setattr(settings, "vault_token", "")
    with pytest.raises(SolanaClientError, match="VAULT_ADDR and VAULT_TOKEN"):
        await _load_operator()


async def test_load_vault_operator_wraps_5xx_and_logs_failure(
    monkeypatch, fake_log_calls
):
    monkeypatch.setattr(settings, "vault_addr", "https://vault.example.com")
    monkeypatch.setattr(settings, "vault_token", "test-token")

    fake_client = _make_fake_async_client(
        get_response=_FakeResponse(500, text="internal error")
    )
    monkeypatch.setattr(signer_backends.httpx, "AsyncClient", fake_client)

    with pytest.raises(VaultSignerError, match="vault key lookup failed"):
        await load_vault_operator(caller_context="test.ctx", op_kind="sign")

    assert len(fake_log_calls) == 1
    assert fake_log_calls[0]["success"] is False
    assert fake_log_calls[0]["caller_context"] == "test.ctx"


# ---------------------------------------------------------------------------
# "vault:v1:<b64>" signature format parsing
# ---------------------------------------------------------------------------


async def test_sign_message_parses_vault_v1_signature_format(monkeypatch):
    raw_sig = b"\x01" * 64  # ed25519 signatures are 64 bytes
    encoded = base64.b64encode(raw_sig).decode("ascii")

    fake_client = _make_fake_async_client(
        post_response=_FakeResponse(
            200, json_data={"data": {"signature": f"vault:v1:{encoded}"}}
        )
    )
    monkeypatch.setattr(signer_backends.httpx, "AsyncClient", fake_client)

    signer = VaultOperatorSigner(
        _addr="https://vault.example.com",
        _token="test-token",
        _key_name="etornie-operator",
        _pubkey=Pubkey.default(),
    )
    result = await signer.sign_message(b"hello world")
    assert result == raw_sig


# ---------------------------------------------------------------------------
# latest_version selection
# ---------------------------------------------------------------------------


async def test_fetch_vault_pubkey_uses_latest_version(monkeypatch):
    raw_key = b"\x02" * 32
    encoded = base64.b64encode(raw_key).decode("ascii")
    stale = base64.b64encode(b"\x00" * 32).decode("ascii")

    fake_client = _make_fake_async_client(
        get_response=_FakeResponse(
            200,
            json_data={
                "data": {
                    "latest_version": 3,
                    "keys": {
                        "1": {"public_key": stale},
                        "2": {"public_key": stale},
                        "3": {"public_key": encoded},
                    },
                }
            },
        )
    )
    monkeypatch.setattr(signer_backends.httpx, "AsyncClient", fake_client)

    pubkey = await _fetch_vault_pubkey(
        "https://vault.example.com", "test-token", "etornie-operator"
    )
    assert pubkey == Pubkey.from_bytes(raw_key)

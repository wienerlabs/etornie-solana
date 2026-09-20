"""Vault-backed operator signer (Transit secrets engine).

Keeps the raw ed25519 private key inside Vault; every signature is
requested over Vault's HTTP API instead of being computed from key
bytes held in this process's memory. Configuration is read from
``app.config.settings`` (SIGNER_BACKEND / VAULT_* env vars):

  VAULT_ADDR              e.g. https://vault.internal:8200
  VAULT_TOKEN             Vault auth token with sign+read on the
                          configured Transit key
  VAULT_TRANSIT_KEY_NAME  Transit key name, default "etornie-operator"

The Vault Transit key must be created with ``type=ed25519``:

    vault secrets enable transit   # once per Vault
    vault write -f transit/keys/etornie-operator type=ed25519
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.config import settings
from app.security.operator_key import log_operator_access


class OperatorSigner(Protocol):
    """Structural type shared by every operator signer backend.

    Both ``LocalKeypairSigner`` (wrapping the local-file backend's
    solders.Keypair) and ``VaultOperatorSigner`` below satisfy this
    shape without needing to inherit from anything — Python's
    structural typing (Protocol) just checks that ``.pubkey()`` and
    ``.sign_message(bytes)`` exist with matching signatures.

    ``sign_message`` is async on this Protocol — even though the
    local-file backend's underlying signing math is synchronous and
    fast — so every call site can uniformly ``await`` it regardless of
    which backend is active. The Vault backend's signature request is
    a real network round-trip and must never block the event loop.
    """

    def pubkey(self) -> Pubkey: ...

    async def sign_message(self, message: bytes) -> bytes: ...


@dataclass(frozen=True)
class LocalKeypairSigner:
    """Adapts a solders.Keypair to the async OperatorSigner shape.

    The actual ed25519 signing here is synchronous, in-process, and
    fast (no I/O) — there is no event-loop-blocking concern for this
    backend. The wrapper exists purely so both backends present the
    same async ``sign_message`` interface to callers in client.py.

    ``secret()`` is intentionally exposed here even though it is not
    part of the OperatorSigner Protocol: callers that need the raw key
    material (currently only the Stripe compliance anti-replay secret
    derivation, see compliance/service.py) detect via
    ``hasattr(signer, "secret")`` whether the active backend can
    provide it at all. VaultOperatorSigner below has no such method,
    so that check correctly fails closed under SIGNER_BACKEND=vault
    instead of ever falling back to public key bytes.
    """

    _keypair: Keypair

    def pubkey(self) -> Pubkey:
        return self._keypair.pubkey()

    async def sign_message(self, message: bytes) -> bytes:
        return bytes(self._keypair.sign_message(message))

    def secret(self) -> bytes:
        return bytes(self._keypair.secret())


class VaultSignerError(RuntimeError):
    """Raised when Vault Transit config or a Vault API call is invalid."""


def _vault_config() -> tuple[str, str, str]:
    addr = settings.vault_addr.strip().rstrip("/")
    token = settings.vault_token.strip()
    key_name = settings.vault_transit_key_name.strip()
    if not addr or not token:
        raise VaultSignerError(
            "SIGNER_BACKEND=vault requires VAULT_ADDR and VAULT_TOKEN "
            "to be set"
        )
    return addr, token, key_name


@dataclass(frozen=True)
class VaultOperatorSigner:
    """Drop-in replacement for solders.Keypair, backed by Vault Transit.

    Only implements the two methods the OperatorSigner Protocol
    requires: ``pubkey()`` and async ``sign_message(bytes)``.
    """

    _addr: str
    _token: str = field(repr=False)
    _key_name: str
    _pubkey: Pubkey

    def pubkey(self) -> Pubkey:
        return self._pubkey

    async def sign_message(self, message: bytes) -> bytes:
        url = f"{self._addr}/v1/transit/sign/{self._key_name}"
        body = {"input": base64.b64encode(message).decode("ascii")}
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            resp = await http_client.post(
                url,
                json=body,
                headers={"X-Vault-Token": self._token},
            )
        if resp.status_code != 200:
            raise VaultSignerError(
                f"vault sign failed ({resp.status_code}): "
                f"{resp.text[:300]}"
            )
        signature_field = resp.json()["data"]["signature"]
        # Format: "vault:v1:<base64 sig>"
        b64_sig = signature_field.split(":", 2)[-1]
        return base64.b64decode(b64_sig)


async def _fetch_vault_pubkey(
    addr: str, token: str, key_name: str
) -> Pubkey:
    url = f"{addr}/v1/transit/keys/{key_name}"
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        resp = await http_client.get(
            url, headers={"X-Vault-Token": token}
        )
    if resp.status_code != 200:
        raise VaultSignerError(
            f"vault key lookup failed ({resp.status_code}): "
            f"{resp.text[:300]}"
        )
    data = resp.json()["data"]
    latest_version = str(data["latest_version"])
    raw_b64 = data["keys"][latest_version]["public_key"]
    raw = base64.b64decode(raw_b64)
    # Vault returns the raw 32-byte ed25519 public key for this key
    # type; if a future Vault version wraps it (DER/SPKI), the actual
    # key material is always the last 32 bytes.
    raw = raw[-32:]
    return Pubkey.from_bytes(raw)


async def load_vault_operator(
    *, caller_context: str = "unknown", op_kind: str = "sign"
) -> VaultOperatorSigner:
    """Build a VaultOperatorSigner, auditing the access like the file backend."""
    try:
        addr, token, key_name = _vault_config()
        pubkey = await _fetch_vault_pubkey(addr, token, key_name)
    except VaultSignerError as exc:
        log_operator_access(
            caller_context=caller_context,
            op_kind=op_kind,
            success=False,
            note=str(exc)[:480],
        )
        raise
    log_operator_access(
        caller_context=caller_context,
        op_kind=op_kind,
        success=True,
        note=f"vault:{key_name}",
    )
    return VaultOperatorSigner(
        _addr=addr, _token=token, _key_name=key_name, _pubkey=pubkey
    )

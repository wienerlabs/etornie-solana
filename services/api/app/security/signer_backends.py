"""Vault-backed operator signer (Transit secrets engine).

Keeps the raw ed25519 private key inside Vault; every signature is
requested over Vault's HTTP API instead of being computed from key
bytes held in this process's memory. Configuration (all read at call
time, so tests can monkeypatch env vars freely):

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
import os
from dataclasses import dataclass

import httpx
from solders.pubkey import Pubkey

from app.security.operator_key import log_operator_access


class VaultSignerError(RuntimeError):
    """Raised when Vault Transit config or a Vault API call is invalid."""


def _vault_config() -> tuple[str, str, str]:
    addr = os.environ.get("VAULT_ADDR", "").strip().rstrip("/")
    token = os.environ.get("VAULT_TOKEN", "").strip()
    key_name = os.environ.get(
        "VAULT_TRANSIT_KEY_NAME", "etornie-operator"
    ).strip()
    if not addr or not token:
        raise VaultSignerError(
            "SIGNER_BACKEND=vault requires VAULT_ADDR and VAULT_TOKEN "
            "to be set"
        )
    return addr, token, key_name


@dataclass(frozen=True)
class VaultOperatorSigner:
    """Drop-in replacement for solders.Keypair, backed by Vault Transit.

    Only implements the two methods client.py actually calls on the
    operator object: ``pubkey()`` and ``sign_message(bytes)``.
    """

    _addr: str
    _token: str
    _key_name: str
    _pubkey: Pubkey

    def pubkey(self) -> Pubkey:
        return self._pubkey

    def sign_message(self, message: bytes) -> bytes:
        url = f"{self._addr}/v1/transit/sign/{self._key_name}"
        body = {"input": base64.b64encode(message).decode("ascii")}
        resp = httpx.post(
            url,
            json=body,
            headers={"X-Vault-Token": self._token},
            timeout=10.0,
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


def _fetch_vault_pubkey(addr: str, token: str, key_name: str) -> Pubkey:
    url = f"{addr}/v1/transit/keys/{key_name}"
    resp = httpx.get(url, headers={"X-Vault-Token": token}, timeout=10.0)
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


def load_vault_operator(
    *, caller_context: str = "unknown", op_kind: str = "sign"
) -> VaultOperatorSigner:
    """Build a VaultOperatorSigner, auditing the access like the file backend."""
    try:
        addr, token, key_name = _vault_config()
        pubkey = _fetch_vault_pubkey(addr, token, key_name)
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

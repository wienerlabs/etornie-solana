"""Client for the etornie-attestation Anchor program on Solana devnet.

Sponsored-transaction pattern:
  1. ``build_attestation_instruction_payload`` returns everything the
     frontend needs to construct the tx via @solana/web3.js (instruction
     data + account metas + fresh blockhash + operator + PDA).
  2. Frontend builds the VersionedTransaction, has the user's Phantom
     wallet sign it (creator signature), and sends the serialized tx
     back to the backend.
  3. ``finalize_sponsored_attestation_tx`` re-signs the operator slot on
     that tx using our keypair, submits the fully-signed tx to devnet,
     and waits for confirmation.

Doing the tx construction on the frontend with @solana/web3.js avoids
any solders/web3.js serialization mismatch that previously broke
signature verification.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction

from app.config import settings

logger = logging.getLogger(__name__)

_IX_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:create_case_attestation"
).digest()[:8]


@dataclass(frozen=True)
class AttestationInstructionPayload:
    """Everything the frontend needs to build and sign the attestation tx."""

    program_id: str
    operator: str
    pda: str
    ix_data_b64: str
    recent_blockhash: str


class SolanaClientError(RuntimeError):
    """Raised when an attestation build/verify step fails."""


def _resolve_operator_path() -> Path:
    """Resolve the operator key path relative to the API service root."""
    configured = Path(settings.solana_operator_key_path)
    if configured.is_absolute():
        return configured
    return Path.cwd() / configured


def _load_operator() -> Keypair:
    path = _resolve_operator_path()
    if not path.exists():
        raise SolanaClientError(f"operator key not found at {path}")
    raw = json.loads(path.read_text())
    return Keypair.from_bytes(bytes(raw))


def derive_attestation_pda(case_id: bytes) -> tuple[Pubkey, int]:
    """Derive the case-attestation PDA for a 16-byte case id."""
    if len(case_id) != 16:
        raise ValueError(f"case_id must be 16 bytes, got {len(case_id)}")
    program_id = Pubkey.from_string(settings.solana_attestation_program_id)
    return Pubkey.find_program_address([b"case", case_id], program_id)


def canonicalize_metadata(payload: dict) -> bytes:
    """SHA-256 of a canonical JSON representation of case metadata."""
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).digest()


async def build_attestation_instruction_payload(
    case_id: bytes,
    metadata_hash: bytes,
    client_wallet: Pubkey,
) -> AttestationInstructionPayload:
    """Build the create_case_attestation instruction payload.

    Returns the raw pieces (program id, account metas, ix data, recent
    blockhash) for the frontend to assemble into a VersionedTransaction
    via @solana/web3.js.
    """
    if len(case_id) != 16:
        raise ValueError(f"case_id must be 16 bytes, got {len(case_id)}")
    if len(metadata_hash) != 32:
        raise ValueError(
            f"metadata_hash must be 32 bytes, got {len(metadata_hash)}"
        )

    program_id = Pubkey.from_string(settings.solana_attestation_program_id)
    operator = _load_operator()
    pda, _bump = derive_attestation_pda(case_id)

    ix_data = (
        _IX_DISCRIMINATOR + case_id + metadata_hash + bytes(client_wallet)
    )

    async with AsyncClient(settings.solana_cluster_url) as client:
        latest = await client.get_latest_blockhash()
        blockhash = str(latest.value.blockhash)

    return AttestationInstructionPayload(
        program_id=str(program_id),
        operator=str(operator.pubkey()),
        pda=str(pda),
        ix_data_b64=base64.b64encode(ix_data).decode("ascii"),
        recent_blockhash=blockhash,
    )


async def finalize_sponsored_attestation_tx(
    signed_tx_bytes: bytes,
) -> tuple[str, Pubkey]:
    """Add the operator signature to a user-signed tx and submit it.

    ``signed_tx_bytes`` is a VersionedTransaction serialized by the
    frontend after the user signed it via Phantom; the operator sig slot
    is still empty. We sign that slot here and submit the fully-signed
    tx to devnet.

    Returns ``(tx_signature, program_id)``. The program id is returned
    only so the caller can sanity-check it if needed.
    """
    operator = _load_operator()

    tx = VersionedTransaction.from_bytes(signed_tx_bytes)
    message = tx.message

    # Verify the operator is the expected fee payer (index 0 signer).
    expected_operator = operator.pubkey()
    signer_pubkeys = message.account_keys[: message.header.num_required_signatures]
    if not signer_pubkeys or signer_pubkeys[0] != expected_operator:
        raise SolanaClientError(
            "fee payer in submitted tx does not match backend operator"
        )

    # Sign the same message bytes that the user signed over.
    operator_sig = operator.sign_message(bytes(message))

    # Replace the operator slot (index 0) with our signature; keep the
    # user's signature in slot 1 untouched.
    new_sigs = list(tx.signatures)
    if not new_sigs:
        raise SolanaClientError("submitted tx has no signature slots")
    new_sigs[0] = operator_sig

    final_tx = VersionedTransaction.populate(message, new_sigs)

    async with AsyncClient(settings.solana_cluster_url) as client:
        resp = await client.send_transaction(final_tx)
        signature = resp.value
        await client.confirm_transaction(signature, commitment=Confirmed)

    return str(signature), Pubkey.from_string(
        settings.solana_attestation_program_id
    )


async def verify_attestation_pda(case_id: bytes) -> str | None:
    """Return the attestation PDA address iff it exists on devnet.

    Used by the confirm endpoint: if the PDA was initialized by our
    program, then a valid create_case_attestation tx was executed for
    ``case_id`` — that is sufficient proof for the backend to persist the
    attestation.
    """
    program_id = Pubkey.from_string(settings.solana_attestation_program_id)
    pda, _ = derive_attestation_pda(case_id)

    async with AsyncClient(settings.solana_cluster_url) as client:
        resp = await client.get_account_info(pda, commitment=Confirmed)
        if resp.value is None:
            return None
        if resp.value.owner != program_id:
            return None
        return str(pda)

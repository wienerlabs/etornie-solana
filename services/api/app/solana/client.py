"""Client for the etornie-attestation Anchor program on Solana devnet.

Builds `create_case_attestation` instructions for sponsored transactions:
the backend operator partially signs (and pays the fee), while the user's
Phantom wallet adds the final creator signature before submission. The
program was upgraded to require both signers, so neither half of the tx
alone is sufficient.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Final

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction

from app.config import settings

logger = logging.getLogger(__name__)

_IX_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:create_case_attestation"
).digest()[:8]


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


async def build_create_case_attestation_tx(
    case_id: bytes,
    metadata_hash: bytes,
    creator: Pubkey,
    client_wallet: Pubkey,
) -> tuple[bytes, str]:
    """Build a sponsored create_case_attestation transaction.

    Signed by operator (fee payer) only; the creator signature slot is
    zeroed so the frontend wallet can fill it before submitting.

    Returns ``(tx_bytes, pda_address)`` where ``tx_bytes`` is a serialized
    VersionedTransaction ready to be base64-encoded for transport.
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

    ix = Instruction(
        program_id=program_id,
        data=ix_data,
        accounts=[
            AccountMeta(pubkey=pda, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=operator.pubkey(),
                is_signer=True,
                is_writable=True,
            ),
            AccountMeta(pubkey=creator, is_signer=True, is_writable=False),
            AccountMeta(
                pubkey=SYSTEM_PROGRAM_ID,
                is_signer=False,
                is_writable=False,
            ),
        ],
    )

    async with AsyncClient(settings.solana_cluster_url) as client:
        latest = await client.get_latest_blockhash()
        blockhash = latest.value.blockhash

    msg = MessageV0.try_compile(
        payer=operator.pubkey(),
        instructions=[ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    operator_sig = operator.sign_message(bytes(msg))
    # Signature order matches the required-signers prefix of account_keys:
    # payer (operator) first, then creator. Creator slot is empty for the
    # wallet to fill.
    sigs = [operator_sig, Signature.default()]
    tx = VersionedTransaction.populate(msg, sigs)
    return bytes(tx), str(pda)


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

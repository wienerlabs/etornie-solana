"""Client for the etornie-attestation Anchor program on Solana devnet.

Submits `create_case_attestation` instructions on behalf of the backend
operator keypair. The instruction is hand-encoded (Anchor uses the first
8 bytes of sha256("global:<ix_name>") as a discriminator followed by the
borsh-packed arguments) to avoid pulling in the full anchorpy client for
a single call.
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
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction

from app.config import settings

logger = logging.getLogger(__name__)

_IX_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:create_case_attestation"
).digest()[:8]


class SolanaClientError(RuntimeError):
    """Raised when an attestation submission fails."""


def _resolve_operator_path() -> Path:
    """Resolve the operator key path relative to the API service root.

    The setting is stored as a path relative to services/api (the CWD of
    the running uvicorn process), so a bare filename like
    ``keys/operator.json`` lands at ``services/api/keys/operator.json``.
    """
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


async def create_case_attestation(
    case_id: bytes,
    metadata_hash: bytes,
    creator: Pubkey,
) -> tuple[str, str]:
    """Submit a create_case_attestation tx to devnet.

    Returns ``(tx_signature, pda_address)``.
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
        _IX_DISCRIMINATOR + case_id + metadata_hash + bytes(creator)
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
        tx = VersionedTransaction(msg, [operator])

        send_resp = await client.send_transaction(tx)
        signature = send_resp.value
        logger.info(
            "attestation submitted",
            extra={"tx": str(signature), "pda": str(pda)},
        )

        await client.confirm_transaction(signature, commitment=Confirmed)

    return str(signature), str(pda)

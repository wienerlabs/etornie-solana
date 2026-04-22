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

import asyncio
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

_UPDATE_IX_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:update_case_attestation"
).digest()[:8]

_MINT_CASE_NFT_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:mint_case_nft"
).digest()[:8]

_TOKEN_2022_PROGRAM_ID: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
_ASSOCIATED_TOKEN_PROGRAM_ID: Final[str] = (
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
_NFT_PROGRAM_ID: Final[str] = "6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF"
_NFT_AUTHORITY_SEED: Final[bytes] = b"case_nft_authority"
_CASE_NFT_RECORD_SEED: Final[bytes] = b"case_nft"

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class AttestationInstructionPayload:
    """Everything the frontend needs to build and sign the attestation tx."""

    program_id: str
    operator: str
    pda: str
    ix_data_b64: str
    recent_blockhash: str


@dataclass(frozen=True)
class UpdateAttestationInstructionPayload:
    """Payload for update_case_attestation (existing PDA, no init)."""

    program_id: str
    operator: str
    pda: str
    ix_data_b64: str
    recent_blockhash: str
    metadata_hash_hex: str
    event_type: int


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


def _read_compact_u16(data: bytes, offset: int) -> tuple[int, int]:
    """Parse a Solana compact-u16 value. Returns (value, new_offset)."""
    value = 0
    shift = 0
    pos = offset
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            break
        shift += 7
        if shift > 21:
            raise SolanaClientError("invalid compact-u16 in tx")
    return value, pos


def _write_compact_u16(value: int) -> bytes:
    """Encode a Solana compact-u16 value."""
    out = bytearray()
    v = value
    while True:
        byte = v & 0x7F
        v >>= 7
        if v == 0:
            out.append(byte)
            break
        out.append(byte | 0x80)
    return bytes(out)


async def finalize_sponsored_attestation_tx(
    signed_tx_bytes: bytes,
) -> tuple[str, Pubkey]:
    """Add the operator signature to a user-signed tx and submit it.

    The tx was serialized on the frontend with the exact message bytes
    Phantom signed over. Re-serializing via solders would risk a
    byte-level mismatch (which invalidates the user's signature), so we
    operate directly on the raw bytes: parse the signature array,
    replace slot 0 with our operator signature, and splice the sig
    array back in front of the untouched message bytes.
    """
    operator = _load_operator()

    num_sigs, sigs_start = _read_compact_u16(signed_tx_bytes, 0)
    if num_sigs == 0:
        raise SolanaClientError("submitted tx has no signature slots")
    sigs_end = sigs_start + num_sigs * 64
    if len(signed_tx_bytes) < sigs_end + 1:
        raise SolanaClientError("submitted tx is truncated")

    original_sigs = [
        signed_tx_bytes[sigs_start + i * 64 : sigs_start + (i + 1) * 64]
        for i in range(num_sigs)
    ]
    msg_bytes = signed_tx_bytes[sigs_end:]

    # The VersionedTransaction is still parseable by solders even with
    # the operator signature slot zeroed; we just do not trust its
    # re-serialization for signature verification.
    tx = VersionedTransaction.from_bytes(signed_tx_bytes)
    message = tx.message

    expected_operator = operator.pubkey()
    signer_pubkeys = message.account_keys[: message.header.num_required_signatures]
    if not signer_pubkeys or signer_pubkeys[0] != expected_operator:
        raise SolanaClientError(
            "fee payer in submitted tx does not match backend operator"
        )


    # Sign the exact bytes the user signed over.
    operator_sig = operator.sign_message(msg_bytes)
    new_sigs = list(original_sigs)
    new_sigs[0] = bytes(operator_sig)

    final_tx_bytes = (
        _write_compact_u16(num_sigs) + b"".join(new_sigs) + msg_bytes
    )

    async with AsyncClient(settings.solana_cluster_url) as client:
        resp = await client.send_raw_transaction(final_tx_bytes)
        signature = resp.value
        await client.confirm_transaction(signature, commitment=Confirmed)

    return str(signature), Pubkey.from_string(
        settings.solana_attestation_program_id
    )


async def build_update_attestation_ix_payload(
    case_id: bytes,
    metadata_hash: bytes,
    event_type: int,
) -> UpdateAttestationInstructionPayload:
    """Build the update_case_attestation instruction payload.

    Returns the ingredients for the frontend to assemble and sign the
    update tx. Does not allocate any PDA: the main CaseAttestation PDA
    must already exist (from a prior create_case_attestation call).
    """
    if len(case_id) != 16:
        raise ValueError(f"case_id must be 16 bytes, got {len(case_id)}")
    if len(metadata_hash) != 32:
        raise ValueError(
            f"metadata_hash must be 32 bytes, got {len(metadata_hash)}"
        )
    if not 0 <= event_type <= 255:
        raise ValueError(f"event_type must fit in u8, got {event_type}")

    program_id = Pubkey.from_string(settings.solana_attestation_program_id)
    operator = _load_operator()
    pda, _bump = derive_attestation_pda(case_id)

    ix_data = (
        _UPDATE_IX_DISCRIMINATOR
        + metadata_hash
        + bytes([event_type])
    )

    async with AsyncClient(settings.solana_cluster_url) as client:
        latest = await client.get_latest_blockhash()
        blockhash = str(latest.value.blockhash)

    return UpdateAttestationInstructionPayload(
        program_id=str(program_id),
        operator=str(operator.pubkey()),
        pda=str(pda),
        ix_data_b64=base64.b64encode(ix_data).decode("ascii"),
        recent_blockhash=blockhash,
        metadata_hash_hex=metadata_hash.hex(),
        event_type=event_type,
    )


@dataclass(frozen=True)
class AccountMeta:
    pubkey: str
    is_signer: bool
    is_writable: bool


@dataclass(frozen=True)
class InstructionPayload:
    program_id: str
    accounts: list[AccountMeta]
    data_b64: str


@dataclass(frozen=True)
class MintClaimPayload:
    """Payload for mint_case_nft sponsored flow (frontend assembles tx)."""

    program_id: str
    operator: str
    client: str
    mint: str
    client_token_account: str
    nft_authority: str
    case_nft_record: str
    ata_ix: InstructionPayload
    mint_ix: InstructionPayload
    recent_blockhash: str


def derive_nft_authority() -> Pubkey:
    program_id = Pubkey.from_string(_NFT_PROGRAM_ID)
    authority, _bump = Pubkey.find_program_address(
        [_NFT_AUTHORITY_SEED], program_id
    )
    return authority


def derive_case_nft_record(case_id: bytes) -> Pubkey:
    if len(case_id) != 16:
        raise ValueError(f"case_id must be 16 bytes, got {len(case_id)}")
    program_id = Pubkey.from_string(_NFT_PROGRAM_ID)
    pda, _bump = Pubkey.find_program_address(
        [_CASE_NFT_RECORD_SEED, case_id], program_id
    )
    return pda


def derive_associated_token_address(
    mint: Pubkey, owner: Pubkey
) -> Pubkey:
    """ATA derivation for the Token-2022 program."""
    token_program_id = Pubkey.from_string(_TOKEN_2022_PROGRAM_ID)
    ata_program_id = Pubkey.from_string(_ASSOCIATED_TOKEN_PROGRAM_ID)
    ata, _bump = Pubkey.find_program_address(
        [bytes(owner), bytes(token_program_id), bytes(mint)],
        ata_program_id,
    )
    return ata


async def run_nft_setup(
    name: str, symbol: str, uri: str
) -> tuple[str, str]:
    """Invoke the Node subprocess that creates the Token-2022 mint.

    Returns (mint_pubkey_base58, setup_tx_signature). Raises
    SolanaClientError on non-zero exit or malformed output.
    """
    operator_path = str(_resolve_operator_path())
    payload = json.dumps(
        {
            "name": name,
            "symbol": symbol,
            "uri": uri,
            "cluster_url": settings.solana_cluster_url,
            "operator_key_path": operator_path,
            "program_id": _NFT_PROGRAM_ID,
        }
    )

    ts_node = _REPO_ROOT / "node_modules" / ".bin" / "ts-node"
    script = _REPO_ROOT / "scripts" / "nft" / "setup_mint.ts"
    if not ts_node.exists():
        raise SolanaClientError(f"ts-node not found at {ts_node}")
    if not script.exists():
        raise SolanaClientError(f"setup script not found at {script}")

    proc = await asyncio.create_subprocess_exec(
        str(ts_node),
        "--transpile-only",
        str(script),
        payload,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_REPO_ROOT),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=90.0
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise SolanaClientError("nft setup subprocess timed out after 90s")

    if proc.returncode != 0:
        raise SolanaClientError(
            f"nft setup failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )

    last_line = stdout.decode("utf-8").strip().splitlines()[-1]
    try:
        result = json.loads(last_line)
        return str(result["mint"]), str(result["setup_tx"])
    except (json.JSONDecodeError, KeyError) as exc:
        raise SolanaClientError(
            f"unexpected nft setup output: {last_line!r}"
        ) from exc


async def run_nft_burn(
    case_id: bytes, mint: str, client_wallet: str
) -> str:
    """Invoke the Node subprocess that burns a Case NFT.

    Operator signs alone; program PDA is freeze authority + permanent
    delegate. Returns the burn tx signature.
    """
    if len(case_id) != 16:
        raise ValueError(f"case_id must be 16 bytes, got {len(case_id)}")

    operator_path = str(_resolve_operator_path())
    payload = json.dumps(
        {
            "case_id_hex": case_id.hex(),
            "mint": mint,
            "client_wallet": client_wallet,
            "cluster_url": settings.solana_cluster_url,
            "operator_key_path": operator_path,
            "program_id": _NFT_PROGRAM_ID,
        }
    )

    ts_node = _REPO_ROOT / "node_modules" / ".bin" / "ts-node"
    script = _REPO_ROOT / "scripts" / "nft" / "burn.ts"

    proc = await asyncio.create_subprocess_exec(
        str(ts_node),
        "--transpile-only",
        str(script),
        payload,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_REPO_ROOT),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=90.0
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise SolanaClientError("nft burn subprocess timed out after 90s")

    if proc.returncode != 0:
        raise SolanaClientError(
            f"nft burn failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )

    last_line = stdout.decode("utf-8").strip().splitlines()[-1]
    try:
        result = json.loads(last_line)
        return str(result["burn_tx"])
    except (json.JSONDecodeError, KeyError) as exc:
        raise SolanaClientError(
            f"unexpected nft burn output: {last_line!r}"
        ) from exc


async def build_mint_claim_payload(
    case_id: bytes,
    mint: str,
    client_wallet: str,
    metadata_uri_hash: bytes,
) -> MintClaimPayload:
    """Build the claim payload the frontend uses to construct + sign the mint tx.

    Returns all account metas + ix data for both ATA create (idempotent)
    and mint_case_nft instructions. The frontend composes them into a
    VersionedTransaction, has the client Phantom wallet sign, and returns
    the signed tx bytes to ``finalize_mint_claim_tx``.
    """
    if len(case_id) != 16:
        raise ValueError(f"case_id must be 16 bytes, got {len(case_id)}")
    if len(metadata_uri_hash) != 32:
        raise ValueError(
            f"metadata_uri_hash must be 32 bytes, got {len(metadata_uri_hash)}"
        )

    operator = _load_operator()
    program_id = Pubkey.from_string(_NFT_PROGRAM_ID)
    token_program = Pubkey.from_string(_TOKEN_2022_PROGRAM_ID)
    ata_program = Pubkey.from_string(_ASSOCIATED_TOKEN_PROGRAM_ID)
    mint_pk = Pubkey.from_string(mint)
    client_pk = Pubkey.from_string(client_wallet)

    nft_authority = derive_nft_authority()
    record_pda = derive_case_nft_record(case_id)
    client_ata = derive_associated_token_address(mint_pk, client_pk)

    mint_ix_data = (
        _MINT_CASE_NFT_DISCRIMINATOR + case_id + metadata_uri_hash
    )
    mint_ix = InstructionPayload(
        program_id=str(program_id),
        accounts=[
            AccountMeta(str(record_pda), False, True),
            AccountMeta(str(nft_authority), False, False),
            AccountMeta(str(mint_pk), False, True),
            AccountMeta(str(client_ata), False, True),
            AccountMeta(str(client_pk), True, False),
            AccountMeta(str(operator.pubkey()), True, True),
            AccountMeta(str(token_program), False, False),
            AccountMeta(str(SYSTEM_PROGRAM_ID), False, False),
        ],
        data_b64=base64.b64encode(mint_ix_data).decode("ascii"),
    )

    # ATA idempotent create: single 0x01 byte (discriminator in spl-ata).
    ata_ix = InstructionPayload(
        program_id=str(ata_program),
        accounts=[
            AccountMeta(str(operator.pubkey()), True, True),
            AccountMeta(str(client_ata), False, True),
            AccountMeta(str(client_pk), False, False),
            AccountMeta(str(mint_pk), False, False),
            AccountMeta(str(SYSTEM_PROGRAM_ID), False, False),
            AccountMeta(str(token_program), False, False),
        ],
        data_b64=base64.b64encode(bytes([1])).decode("ascii"),
    )

    async with AsyncClient(settings.solana_cluster_url) as rpc:
        latest = await rpc.get_latest_blockhash()
        blockhash = str(latest.value.blockhash)

    return MintClaimPayload(
        program_id=str(program_id),
        operator=str(operator.pubkey()),
        client=str(client_pk),
        mint=str(mint_pk),
        client_token_account=str(client_ata),
        nft_authority=str(nft_authority),
        case_nft_record=str(record_pda),
        ata_ix=ata_ix,
        mint_ix=mint_ix,
        recent_blockhash=blockhash,
    )


async def finalize_mint_claim_tx(signed_tx_bytes: bytes) -> str:
    """Add the operator signature to a user-signed mint_case_nft tx, submit.

    Mirrors ``finalize_sponsored_attestation_tx`` — operates on raw bytes
    to avoid any re-serialization that could break the client's
    signature. Returns the confirmed signature.
    """
    operator = _load_operator()

    num_sigs, sigs_start = _read_compact_u16(signed_tx_bytes, 0)
    if num_sigs == 0:
        raise SolanaClientError("submitted tx has no signature slots")
    sigs_end = sigs_start + num_sigs * 64
    if len(signed_tx_bytes) < sigs_end + 1:
        raise SolanaClientError("submitted tx is truncated")

    original_sigs = [
        signed_tx_bytes[sigs_start + i * 64 : sigs_start + (i + 1) * 64]
        for i in range(num_sigs)
    ]
    msg_bytes = signed_tx_bytes[sigs_end:]

    tx = VersionedTransaction.from_bytes(signed_tx_bytes)
    message = tx.message
    expected_operator = operator.pubkey()
    signer_pubkeys = message.account_keys[
        : message.header.num_required_signatures
    ]
    if not signer_pubkeys or signer_pubkeys[0] != expected_operator:
        raise SolanaClientError(
            "fee payer in submitted mint tx does not match backend operator"
        )

    operator_sig = operator.sign_message(msg_bytes)
    new_sigs = list(original_sigs)
    new_sigs[0] = bytes(operator_sig)

    final_tx_bytes = (
        _write_compact_u16(num_sigs) + b"".join(new_sigs) + msg_bytes
    )

    async with AsyncClient(settings.solana_cluster_url) as rpc:
        resp = await rpc.send_raw_transaction(final_tx_bytes)
        signature = resp.value
        await rpc.confirm_transaction(signature, commitment=Confirmed)

    return str(signature)


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

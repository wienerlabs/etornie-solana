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
from solana.rpc.core import RPCException
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

_VERIFY_PROOF_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:verify_proof"
).digest()[:8]

_VERIFY_FILE_OWNERSHIP_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:verify_file_ownership_proof"
).digest()[:8]

_VERIFY_COMPLIANCE_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"global:verify_compliance_proof"
).digest()[:8]

_PROOF_RECORD_SEED: Final[bytes] = b"proof"
_FILE_OWNERSHIP_SEED: Final[bytes] = b"file-ownership"
_FILE_OWNERSHIP_PUBLIC_INPUT_COUNT: Final[int] = 3
_COMPLIANCE_SEED: Final[bytes] = b"compliance"
_COMPLIANCE_PUBLIC_INPUT_COUNT: Final[int] = 3

_TOKEN_2022_PROGRAM_ID: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
_ASSOCIATED_TOKEN_PROGRAM_ID: Final[str] = (
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
_NFT_PROGRAM_ID: Final[str] = "6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF"
_NFT_AUTHORITY_SEED: Final[bytes] = b"case_nft_authority"
_CASE_NFT_RECORD_SEED: Final[bytes] = b"case_nft"

def _resolve_repo_root() -> Path:
    """Locate the repo root for Node helper scripts (NFT setup/burn).

    The expected dev layout puts this file at services/api/app/solana/client.py,
    so parents[4] is the repo root. Inside a container that ships only the api
    service (e.g. Railway via services/api/Dockerfile) the depth is shallower;
    we fall back to the deepest available ancestor so import does not fail. The
    NFT subprocess helpers will surface a clear SolanaClientError at call time
    if ts-node/scripts are not actually present.
    """
    here = Path(__file__).resolve()
    parents = list(here.parents)
    return parents[4] if len(parents) > 4 else parents[-1]


_REPO_ROOT: Final[Path] = _resolve_repo_root()

_SYSTEM_TRANSFER_DISCRIMINATOR: Final[bytes] = (2).to_bytes(4, "little")


def sum_user_transfers_to_treasury(
    message,
    operator: Pubkey,
    treasury: Pubkey,
) -> int:
    account_keys = list(message.account_keys)
    num_required_signatures = message.header.num_required_signatures
    signer_indices = set(range(num_required_signatures))
    operator_indices = {
        index
        for index, key in enumerate(account_keys)
        if key == operator
    }

    total = 0
    for instruction in message.instructions:
        program_index = instruction.program_id_index
        if program_index >= len(account_keys):
            continue
        if account_keys[program_index] != SYSTEM_PROGRAM_ID:
            continue
        data = bytes(instruction.data)
        if len(data) < 12:
            continue
        if data[0:4] != _SYSTEM_TRANSFER_DISCRIMINATOR:
            continue
        accounts = bytes(instruction.accounts)
        if len(accounts) < 2:
            continue
        source_index = accounts[0]
        destination_index = accounts[1]
        if source_index >= len(account_keys):
            continue
        if destination_index >= len(account_keys):
            continue
        if source_index not in signer_indices:
            continue
        if source_index in operator_indices:
            continue
        if account_keys[destination_index] != treasury:
            continue
        total += int.from_bytes(data[4:12], "little")
    return total


def assert_treasury_fee_paid(
    message,
    operator: Pubkey,
    min_lamports: int,
) -> None:
    if not settings.fee_treasury_vault:
        return
    if min_lamports <= 0:
        return
    treasury = Pubkey.from_string(settings.fee_treasury_vault)
    paid = sum_user_transfers_to_treasury(message, operator, treasury)
    if paid < min_lamports:
        raise SolanaClientError(
            "required fee transfer to treasury is missing or insufficient: "
            f"expected at least {min_lamports} lamports from the user to "
            f"{treasury}, found {paid}"
        )


def _is_user_fee_transfer(
    instruction,
    account_keys,
    signer_indices,
    operator_indices,
    treasury: Pubkey,
) -> bool:
    data = bytes(instruction.data)
    if len(data) < 12:
        return False
    if data[0:4] != _SYSTEM_TRANSFER_DISCRIMINATOR:
        return False
    accounts = bytes(instruction.accounts)
    if len(accounts) < 2:
        return False
    source_index = accounts[0]
    destination_index = accounts[1]
    if source_index >= len(account_keys):
        return False
    if destination_index >= len(account_keys):
        return False
    if source_index not in signer_indices:
        return False
    if source_index in operator_indices:
        return False
    return account_keys[destination_index] == treasury


def assert_only_expected_programs(
    message,
    operator: Pubkey,
    allowed_program_ids: set,
    fee_treasury: Pubkey | None,
) -> None:
    if getattr(message, "address_table_lookups", None):
        raise SolanaClientError(
            "submitted tx uses address lookup tables, which are not allowed"
        )
    account_keys = list(message.account_keys)
    signer_indices = set(range(message.header.num_required_signatures))
    operator_indices = {
        index for index, key in enumerate(account_keys) if key == operator
    }
    for instruction in message.instructions:
        program_index = instruction.program_id_index
        if program_index >= len(account_keys):
            raise SolanaClientError(
                "submitted tx references an out of range program index"
            )
        program_id = account_keys[program_index]
        if program_id == SYSTEM_PROGRAM_ID:
            if fee_treasury is None or not _is_user_fee_transfer(
                instruction,
                account_keys,
                signer_indices,
                operator_indices,
                fee_treasury,
            ):
                raise SolanaClientError(
                    "submitted tx contains an unexpected system instruction"
                )
        elif program_id not in allowed_program_ids:
            raise SolanaClientError(
                f"submitted tx invokes an unexpected program: {program_id}"
            )


@dataclass(frozen=True)
class AttestationInstructionPayload:
    """Everything the frontend needs to build and sign the attestation tx."""

    program_id: str
    operator: str
    pda: str
    ix_data_b64: str
    recent_blockhash: str
    fee_treasury: str | None = None
    fee_lamports: int = 0


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


class ProofAlreadyRecorded(SolanaClientError):
    """Raised when the on-chain ZK verifier rejects a duplicate proof.

    Matches Anchor error code 6003 (ReplayedProof). The proof is
    already on-chain for this (operator, file_hash) pair, so the
    submission is logically a no-op rather than a failure.
    """


def _materialize_operator_key_file() -> Path | None:
    """Persist SOLANA_OPERATOR_KEY_JSON to /tmp so subprocesses can read it.

    The TS NFT scripts (scripts/nft/*.ts) accept only a file path. On
    platforms without a persistent filesystem (Railway, Fly) the operator
    keypair is supplied via env var; we write it to a 0600 tmp file once
    at startup and reuse that path. Returns None when the env var is empty
    so dev environments keep using the configured file directly.
    """
    inline = settings.solana_operator_key_json.strip()
    if not inline:
        return None
    try:
        json.loads(inline)
    except json.JSONDecodeError as exc:
        raise SolanaClientError(
            f"solana_operator_key_json is not valid JSON: {exc}"
        ) from exc
    path = Path("/tmp/operator.json")
    path.write_text(inline)
    try:
        path.chmod(0o600)
    except OSError:
        # /tmp on some platforms rejects chmod; not fatal.
        pass
    return path


_OPERATOR_TEMP_PATH: Final[Path | None] = _materialize_operator_key_file()


def _resolve_operator_path() -> Path:
    """Resolve the operator key path used by both Python and TS subprocesses.

    When SOLANA_OPERATOR_KEY_JSON is set the env var is materialized to
    /tmp/operator.json at startup and that path is returned. Otherwise we
    fall back to settings.solana_operator_key_path (relative to cwd).
    """
    if _OPERATOR_TEMP_PATH is not None:
        return _OPERATOR_TEMP_PATH
    configured = Path(settings.solana_operator_key_path)
    if configured.is_absolute():
        return configured
    return Path.cwd() / configured


def _load_operator(caller_context: str = "unknown", op_kind: str = "sign") -> Keypair:
    """Load the operator keypair.

    Adds two security improvements over reading the file straight:
    1. The on-disk content is passed through
       ``security.operator_key.decrypt_if_needed`` which transparently
       decrypts a Fernet-encrypted blob when the ``etornie-key-v1:``
       prefix is present and the master key env var is set.
    2. Every load attempt — success or failure — writes one row to
       ``operator_key_access_log`` so an operator can audit who/what
       reached for the key after the fact.
    """
    from app.security.operator_key import (
        OperatorKeyError,
        decrypt_if_needed,
        log_operator_access,
    )

    path = _resolve_operator_path()
    if not path.exists():
        log_operator_access(
            caller_context=caller_context,
            op_kind=op_kind,
            success=False,
            note=f"operator key not found at {path}",
        )
        raise SolanaClientError(
            f"operator key not found at {path} and "
            "SOLANA_OPERATOR_KEY_JSON is empty"
        )
    try:
        plaintext = decrypt_if_needed(path.read_text())
        raw = json.loads(plaintext)
        keypair = Keypair.from_bytes(bytes(raw))
    except OperatorKeyError as exc:
        log_operator_access(
            caller_context=caller_context,
            op_kind=op_kind,
            success=False,
            note=str(exc)[:480],
        )
        raise SolanaClientError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log_operator_access(
            caller_context=caller_context,
            op_kind=op_kind,
            success=False,
            note=f"parse failed: {type(exc).__name__}",
        )
        raise SolanaClientError(
            f"operator key parse failed: {exc}"
        ) from exc
    log_operator_access(
        caller_context=caller_context,
        op_kind=op_kind,
        success=True,
    )
    return keypair


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

    fee_treasury = settings.fee_treasury_vault or None
    fee_lamports = settings.registration_fee_lamports if fee_treasury else 0

    return AttestationInstructionPayload(
        program_id=str(program_id),
        operator=str(operator.pubkey()),
        pda=str(pda),
        ix_data_b64=base64.b64encode(ix_data).decode("ascii"),
        recent_blockhash=blockhash,
        fee_treasury=fee_treasury,
        fee_lamports=fee_lamports,
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
    require_registration_fee: bool = False,
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

    fee_treasury = (
        Pubkey.from_string(settings.fee_treasury_vault)
        if settings.fee_treasury_vault
        else None
    )
    attestation_program = Pubkey.from_string(
        settings.solana_attestation_program_id
    )
    if require_registration_fee:
        assert_treasury_fee_paid(
            message, expected_operator, settings.registration_fee_lamports
        )
        assert_only_expected_programs(
            message, expected_operator, {attestation_program}, fee_treasury
        )
    else:
        assert_only_expected_programs(
            message, expected_operator, {attestation_program}, None
        )

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
    fee_treasury: str | None = None
    fee_lamports: int = 0


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

    fee_treasury = settings.fee_treasury_vault or None
    fee_lamports = settings.mint_fee_lamports if fee_treasury else 0

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
        fee_treasury=fee_treasury,
        fee_lamports=fee_lamports,
    )


async def finalize_mint_claim_tx(signed_tx_bytes: bytes) -> str:
    """Add the operator signature to a user-signed mint_case_nft tx, submit.

    Mirrors ``finalize_sponsored_attestation_tx`` - operates on raw bytes
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

    fee_treasury = (
        Pubkey.from_string(settings.fee_treasury_vault)
        if settings.fee_treasury_vault
        else None
    )
    assert_treasury_fee_paid(
        message, expected_operator, settings.mint_fee_lamports
    )
    assert_only_expected_programs(
        message,
        expected_operator,
        {
            Pubkey.from_string(_NFT_PROGRAM_ID),
            Pubkey.from_string(_ASSOCIATED_TOKEN_PROGRAM_ID),
        },
        fee_treasury,
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


@dataclass(frozen=True)
class VerifyProofPayload:
    """Ingredients for the frontend to build the sponsored verify_proof tx.

    The frontend composes a VersionedTransaction with `fee_payer` as the tx
    fee payer (slot 0 of the required-signers list) and `user` as slot 1.
    Phantom signs slot 1 only; the backend fills in slot 0 in
    ``finalize_sponsored_verify_tx`` before submitting.
    """

    program_id: str
    fee_payer: str
    user: str
    proof_record: str
    ix_data_b64: str
    recent_blockhash: str


def derive_proof_record_pda(
    user: Pubkey, journal_digest: bytes
) -> tuple[Pubkey, int]:
    """Derive the ProofRecord PDA for (user, journal_digest)."""
    if len(journal_digest) != 32:
        raise ValueError(
            f"journal_digest must be 32 bytes, got {len(journal_digest)}"
        )
    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    return Pubkey.find_program_address(
        [_PROOF_RECORD_SEED, bytes(user), journal_digest],
        program_id,
    )


async def build_verify_proof_ix_payload(
    user: Pubkey,
    proof_a: bytes,
    proof_b: bytes,
    proof_c: bytes,
    public_inputs: list[bytes],
    journal_digest: bytes,
) -> VerifyProofPayload:
    """Build the verify_proof instruction payload for the sponsored flow.

    ix_data layout:
        discriminator (8)
        || proof_a (64)
        || proof_b (128)
        || proof_c (64)
        || public_inputs flattened (N * 32, fixed-size array, no prefix)
        || journal_digest (32)

    The PUBLIC_INPUT_COUNT is pinned to 1 in the on-chain program, so the
    array is fixed-size and serialised without a length prefix - matches
    Anchor's borsh layout for `[[u8; 32]; 1]`.
    """
    if len(proof_a) != 64:
        raise ValueError(f"proof_a must be 64 bytes, got {len(proof_a)}")
    if len(proof_b) != 128:
        raise ValueError(f"proof_b must be 128 bytes, got {len(proof_b)}")
    if len(proof_c) != 64:
        raise ValueError(f"proof_c must be 64 bytes, got {len(proof_c)}")
    if len(public_inputs) != 1:
        raise ValueError(
            "public_inputs must have exactly 1 entry for the hello_world "
            f"circuit, got {len(public_inputs)}"
        )
    for idx, inp in enumerate(public_inputs):
        if len(inp) != 32:
            raise ValueError(
                f"public_inputs[{idx}] must be 32 bytes, got {len(inp)}"
            )
    if len(journal_digest) != 32:
        raise ValueError(
            f"journal_digest must be 32 bytes, got {len(journal_digest)}"
        )

    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    operator = _load_operator()
    pda, _bump = derive_proof_record_pda(user, journal_digest)

    ix_data = (
        _VERIFY_PROOF_DISCRIMINATOR
        + proof_a
        + proof_b
        + proof_c
        + b"".join(public_inputs)
        + journal_digest
    )

    async with AsyncClient(settings.solana_cluster_url) as client:
        latest = await client.get_latest_blockhash()
        blockhash = str(latest.value.blockhash)

    return VerifyProofPayload(
        program_id=str(program_id),
        fee_payer=str(operator.pubkey()),
        user=str(user),
        proof_record=str(pda),
        ix_data_b64=base64.b64encode(ix_data).decode("ascii"),
        recent_blockhash=blockhash,
    )


async def finalize_sponsored_verify_tx(signed_tx_bytes: bytes) -> str:
    """Add the operator signature to a user-signed verify_proof tx, submit.

    Mirrors ``finalize_sponsored_attestation_tx`` byte-for-byte: parse the
    compact-u16 signature array, splice the operator signature into slot
    0, and forward the raw bytes to the RPC so the user's signature (slot
    1) is never invalidated by re-serialization.

    Returns the confirmed tx signature.
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
    expected_fee_payer = operator.pubkey()
    signer_pubkeys = message.account_keys[
        : message.header.num_required_signatures
    ]
    if not signer_pubkeys or signer_pubkeys[0] != expected_fee_payer:
        raise SolanaClientError(
            "fee payer in submitted verify tx does not match backend operator"
        )

    operator_sig = operator.sign_message(msg_bytes)
    new_sigs = list(original_sigs)
    new_sigs[0] = bytes(operator_sig)

    final_tx_bytes = (
        _write_compact_u16(num_sigs) + b"".join(new_sigs) + msg_bytes
    )

    async with AsyncClient(settings.solana_cluster_url) as rpc:
        try:
            resp = await rpc.send_raw_transaction(final_tx_bytes)
        except RPCException as exc:
            # Anchor error 6003 (=0x1773) "ReplayedProof": this
            # (operator, file_hash) pair already has a proof PDA.
            # Bubble up a typed exception so the router can return
            # an idempotent success instead of a 500.
            msg = str(exc)
            if "Custom(6003)" in msg or "0x1773" in msg or "ReplayedProof" in msg:
                raise ProofAlreadyRecorded(
                    "proof already recorded for this operator + file hash"
                ) from exc
            raise SolanaClientError(f"send_raw_transaction failed: {exc}") from exc
        signature = resp.value
        await rpc.confirm_transaction(signature, commitment=Confirmed)

    return str(signature)


_FILE_OWNERSHIP_RECORD_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"account:FileOwnershipRecord"
).digest()[:8]


@dataclass(frozen=True)
class FileOwnershipRecord:
    """Decoded FileOwnershipRecord PDA account (matches Anchor layout).

    Anchor account layout:
        discriminator  (8)   = sha256("account:FileOwnershipRecord")[:8]
        owner          (32)  Pubkey of the claim owner
        file_hash      (32)  sha256 of the file
        commitment     (32)  Poseidon(secret, fh_hi, fh_lo), BE 32-byte field element
        verified_at    (8)   i64, seconds since unix epoch (Clock::unix_timestamp)
        bump           (1)
        is_initialized (1)   bool
    """

    owner: str
    file_hash_hex: str
    commitment_hex: str
    verified_at: int
    bump: int
    is_initialized: bool


def _decode_file_ownership_record(data: bytes) -> FileOwnershipRecord:
    """Parse raw account bytes into a FileOwnershipRecord."""
    expected_len = 8 + 32 + 32 + 32 + 8 + 1 + 1  # 114
    if len(data) < expected_len:
        raise SolanaClientError(
            f"FileOwnershipRecord data too short: {len(data)} < {expected_len}"
        )
    if data[:8] != _FILE_OWNERSHIP_RECORD_DISCRIMINATOR:
        raise SolanaClientError(
            "account discriminator does not match FileOwnershipRecord - "
            "PDA may be a different account type"
        )
    owner_bytes = data[8:40]
    file_hash = data[40:72]
    commitment = data[72:104]
    verified_at = int.from_bytes(data[104:112], "little", signed=True)
    bump = data[112]
    is_initialized = data[113] != 0
    return FileOwnershipRecord(
        owner=str(Pubkey.from_bytes(owner_bytes)),
        file_hash_hex=file_hash.hex(),
        commitment_hex=commitment.hex(),
        verified_at=verified_at,
        bump=bump,
        is_initialized=is_initialized,
    )


async def fetch_file_ownership_record(
    pda: Pubkey,
) -> FileOwnershipRecord | None:
    """Read + decode the on-chain FileOwnershipRecord PDA.

    Returns ``None`` when the account does not exist or is not owned by the
    zk-verifier program. Raises :class:`SolanaClientError` on RPC / decode
    failures so callers can surface a 4xx instead of silently accepting
    invalid claims.
    """
    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    async with AsyncClient(settings.solana_cluster_url) as client:
        resp = await client.get_account_info(pda, commitment=Confirmed)
        if resp.value is None:
            return None
        if resp.value.owner != program_id:
            return None
        record = _decode_file_ownership_record(bytes(resp.value.data))
        if not record.is_initialized:
            raise SolanaClientError(
                f"FileOwnershipRecord {pda} exists but is_initialized=false"
            )
        return record


@dataclass(frozen=True)
class VerifyFileOwnershipPayload:
    """Ingredients for the frontend to build the sponsored verify_file_ownership_proof tx.

    Same account-layout pattern as VerifyProofPayload: slot 0 is the
    operator fee-payer (filled in by :func:`finalize_sponsored_verify_tx`
    after the user signs), slot 1 is the claim owner.
    """

    program_id: str
    fee_payer: str
    user: str
    file_ownership_record: str
    ix_data_b64: str
    recent_blockhash: str


def derive_file_ownership_record_pda(
    user: Pubkey, file_hash: bytes
) -> tuple[Pubkey, int]:
    """Derive the FileOwnershipRecord PDA for (user, file_hash).

    Matches `FILE_OWNERSHIP_SEED` in programs/etornie-zk-verifier/src/lib.rs
    and the per-user ownership design (multiple users may independently
    claim the same file).
    """
    if len(file_hash) != 32:
        raise ValueError(
            f"file_hash must be 32 bytes, got {len(file_hash)}"
        )
    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    return Pubkey.find_program_address(
        [_FILE_OWNERSHIP_SEED, bytes(user), file_hash],
        program_id,
    )


async def build_verify_file_ownership_ix_payload(
    user: Pubkey,
    proof_a: bytes,
    proof_b: bytes,
    proof_c: bytes,
    public_inputs: list[bytes],
    file_hash: bytes,
) -> VerifyFileOwnershipPayload:
    """Build the verify_file_ownership_proof instruction payload.

    ix_data layout (borsh):
        discriminator (8)
        || proof_a (64)
        || proof_b (128)
        || proof_c (64)
        || public_inputs flattened (3 * 32 = 96, fixed-size, no prefix)
        || file_hash (32)

    Public inputs must be ordered [fh_hi, fh_lo, commitment] - matches the
    circuit's public signal declaration order in file_ownership.circom.
    """
    if len(proof_a) != 64:
        raise ValueError(f"proof_a must be 64 bytes, got {len(proof_a)}")
    if len(proof_b) != 128:
        raise ValueError(f"proof_b must be 128 bytes, got {len(proof_b)}")
    if len(proof_c) != 64:
        raise ValueError(f"proof_c must be 64 bytes, got {len(proof_c)}")
    if len(public_inputs) != _FILE_OWNERSHIP_PUBLIC_INPUT_COUNT:
        raise ValueError(
            "public_inputs must have exactly "
            f"{_FILE_OWNERSHIP_PUBLIC_INPUT_COUNT} entries for the "
            f"file_ownership circuit, got {len(public_inputs)}"
        )
    for idx, inp in enumerate(public_inputs):
        if len(inp) != 32:
            raise ValueError(
                f"public_inputs[{idx}] must be 32 bytes, got {len(inp)}"
            )
    if len(file_hash) != 32:
        raise ValueError(
            f"file_hash must be 32 bytes, got {len(file_hash)}"
        )

    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    operator = _load_operator()
    pda, _bump = derive_file_ownership_record_pda(user, file_hash)

    ix_data = (
        _VERIFY_FILE_OWNERSHIP_DISCRIMINATOR
        + proof_a
        + proof_b
        + proof_c
        + b"".join(public_inputs)
        + file_hash
    )

    async with AsyncClient(settings.solana_cluster_url) as client:
        latest = await client.get_latest_blockhash()
        blockhash = str(latest.value.blockhash)

    return VerifyFileOwnershipPayload(
        program_id=str(program_id),
        fee_payer=str(operator.pubkey()),
        user=str(user),
        file_ownership_record=str(pda),
        ix_data_b64=base64.b64encode(ix_data).decode("ascii"),
        recent_blockhash=blockhash,
    )


_COMPLIANCE_RECORD_DISCRIMINATOR: Final[bytes] = hashlib.sha256(
    b"account:ComplianceRecord"
).digest()[:8]


@dataclass(frozen=True)
class ComplianceRecord:
    """Decoded ComplianceRecord PDA account (matches Anchor layout).

    Anchor account layout:
        discriminator  (8)   = sha256("account:ComplianceRecord")[:8]
        payer          (32)  Pubkey of the wallet that paid
        query_hash     (32)  sha256 of the AI query plaintext
        commitment     (32)  Poseidon(secret, qh_hi, qh_lo), BE 32-byte field
        verified_at    (8)   i64, seconds since unix epoch
        bump           (1)
        is_initialized (1)   bool
    """

    payer: str
    query_hash_hex: str
    commitment_hex: str
    verified_at: int
    bump: int
    is_initialized: bool


def _decode_compliance_record(data: bytes) -> ComplianceRecord:
    expected_len = 8 + 32 + 32 + 32 + 8 + 1 + 1  # 114
    if len(data) < expected_len:
        raise SolanaClientError(
            f"ComplianceRecord data too short: {len(data)} < {expected_len}"
        )
    if data[:8] != _COMPLIANCE_RECORD_DISCRIMINATOR:
        raise SolanaClientError(
            "account discriminator does not match ComplianceRecord"
        )
    payer_bytes = data[8:40]
    query_hash = data[40:72]
    commitment = data[72:104]
    verified_at = int.from_bytes(data[104:112], "little", signed=True)
    bump = data[112]
    is_initialized = data[113] != 0
    return ComplianceRecord(
        payer=str(Pubkey.from_bytes(payer_bytes)),
        query_hash_hex=query_hash.hex(),
        commitment_hex=commitment.hex(),
        verified_at=verified_at,
        bump=bump,
        is_initialized=is_initialized,
    )


def derive_compliance_record_pda(
    user: Pubkey, query_hash: bytes
) -> tuple[Pubkey, int]:
    """Derive the ComplianceRecord PDA for (user, query_hash).

    Matches `COMPLIANCE_SEED` in programs/etornie-zk-verifier/src/lib.rs -
    per-user, per-query scoping lets two different wallets independently
    pay for the same question while blocking the same wallet from paying
    twice for an already-attested query.
    """
    if len(query_hash) != 32:
        raise ValueError(
            f"query_hash must be 32 bytes, got {len(query_hash)}"
        )
    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    return Pubkey.find_program_address(
        [_COMPLIANCE_SEED, bytes(user), query_hash],
        program_id,
    )


async def fetch_compliance_record(
    pda: Pubkey,
) -> ComplianceRecord | None:
    """Read + decode the on-chain ComplianceRecord PDA.

    Returns ``None`` when the account does not exist or is not owned by
    the zk-verifier program. Raises :class:`SolanaClientError` on RPC or
    decode failures.
    """
    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    async with AsyncClient(settings.solana_cluster_url) as client:
        resp = await client.get_account_info(pda, commitment=Confirmed)
        if resp.value is None:
            return None
        if resp.value.owner != program_id:
            return None
        record = _decode_compliance_record(bytes(resp.value.data))
        if not record.is_initialized:
            raise SolanaClientError(
                f"ComplianceRecord {pda} exists but is_initialized=false"
            )
        return record


async def submit_compliance_proof_tx(
    user: Pubkey,
    proof_a: bytes,
    proof_b: bytes,
    proof_c: bytes,
    public_inputs: list[bytes],
    query_hash: bytes,
) -> tuple[str, Pubkey]:
    """Build, sign (operator only), and submit a verify_compliance_proof tx.

    Unlike the file_ownership sponsored flow, the `user` account is an
    UncheckedAccount on-chain - only the operator signs the tx. The proof
    itself binds the record to the user's wallet because the commitment
    is derived from a wallet-signature-seeded secret.

    Returns ``(signature, compliance_pda)``.
    """
    if len(proof_a) != 64:
        raise ValueError(f"proof_a must be 64 bytes, got {len(proof_a)}")
    if len(proof_b) != 128:
        raise ValueError(f"proof_b must be 128 bytes, got {len(proof_b)}")
    if len(proof_c) != 64:
        raise ValueError(f"proof_c must be 64 bytes, got {len(proof_c)}")
    if len(public_inputs) != _COMPLIANCE_PUBLIC_INPUT_COUNT:
        raise ValueError(
            "public_inputs must have exactly "
            f"{_COMPLIANCE_PUBLIC_INPUT_COUNT} entries for the compliance "
            f"circuit, got {len(public_inputs)}"
        )
    for idx, inp in enumerate(public_inputs):
        if len(inp) != 32:
            raise ValueError(
                f"public_inputs[{idx}] must be 32 bytes, got {len(inp)}"
            )
    if len(query_hash) != 32:
        raise ValueError(
            f"query_hash must be 32 bytes, got {len(query_hash)}"
        )

    from solders.compute_budget import set_compute_unit_limit
    from solders.instruction import AccountMeta as SoldersAccountMeta
    from solders.instruction import Instruction
    from solders.message import MessageV0

    program_id = Pubkey.from_string(settings.solana_zk_verifier_program_id)
    operator = _load_operator()
    pda, _bump = derive_compliance_record_pda(user, query_hash)

    ix_data = (
        _VERIFY_COMPLIANCE_DISCRIMINATOR
        + proof_a
        + proof_b
        + proof_c
        + b"".join(public_inputs)
        + query_hash
    )

    compliance_ix = Instruction(
        program_id=program_id,
        accounts=[
            SoldersAccountMeta(
                pubkey=operator.pubkey(), is_signer=True, is_writable=True
            ),
            SoldersAccountMeta(
                pubkey=user, is_signer=False, is_writable=False
            ),
            SoldersAccountMeta(
                pubkey=pda, is_signer=False, is_writable=True
            ),
            SoldersAccountMeta(
                pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False
            ),
        ],
        data=ix_data,
    )
    compute_ix = set_compute_unit_limit(180_000)

    async with AsyncClient(settings.solana_cluster_url) as rpc:
        latest = await rpc.get_latest_blockhash()
        blockhash = latest.value.blockhash
        message = MessageV0.try_compile(
            payer=operator.pubkey(),
            instructions=[compute_ix, compliance_ix],
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash,
        )
        tx = VersionedTransaction(message, [operator])
        resp = await rpc.send_transaction(tx)
        signature = resp.value
        await rpc.confirm_transaction(signature, commitment=Confirmed)

    return str(signature), pda


async def verify_payment_tx(
    signature: str,
    expected_recipient: Pubkey,
    min_lamports: int,
    expected_memo: str,
) -> None:
    """Validate an on-chain SOL payment tx for the x402 EtornieGPT flow.

    Checks:
      1. tx exists and is finalized (commitment=Confirmed is sufficient
         for devnet).
      2. A SystemProgram.transfer with `expected_recipient` as the
         destination moves at least `min_lamports`.
      3. A Memo program instruction carries exactly `expected_memo`
         (UTF-8 string, typically base58-encoded sha256 binding).

    Raises :class:`SolanaClientError` with a human-readable reason on any
    validation failure. No return value - caller proceeds only if no
    exception is raised.
    """
    from solders.signature import Signature as SolSig

    try:
        sig = SolSig.from_string(signature)
    except Exception as exc:
        raise SolanaClientError(f"invalid payment signature: {exc}") from exc

    async with AsyncClient(settings.solana_cluster_url) as rpc:
        resp = await rpc.get_transaction(
            sig,
            max_supported_transaction_version=0,
            commitment=Confirmed,
        )
    if resp.value is None:
        raise SolanaClientError(
            f"payment tx {signature} not found on devnet"
        )
    tx_info = resp.value
    if tx_info.transaction.meta is None:
        raise SolanaClientError("payment tx has no meta (not yet finalized)")
    if tx_info.transaction.meta.err is not None:
        raise SolanaClientError(
            f"payment tx failed on-chain: {tx_info.transaction.meta.err}"
        )

    # Parse message: account_keys + instructions
    tx = tx_info.transaction.transaction
    try:
        message = tx.message
    except AttributeError as exc:
        raise SolanaClientError(
            "unexpected tx payload shape (no .message)"
        ) from exc

    account_keys = list(message.account_keys)
    recipient_idx: int | None = None
    for i, key in enumerate(account_keys):
        if key == expected_recipient:
            recipient_idx = i
            break
    if recipient_idx is None:
        raise SolanaClientError(
            f"payment tx does not reference expected recipient "
            f"{expected_recipient}"
        )

    # Balance delta on recipient - pre/post balances from meta.
    meta = tx_info.transaction.meta
    pre = meta.pre_balances[recipient_idx]
    post = meta.post_balances[recipient_idx]
    delta = post - pre
    if delta < min_lamports:
        raise SolanaClientError(
            f"payment tx moved {delta} lamports to recipient, "
            f"expected at least {min_lamports}"
        )

    # Scan instructions for a Memo program call carrying the expected memo.
    # solana-py returns `ix.data` as either raw bytes (CompiledInstruction) or
    # a base58-encoded string (UiCompiledInstruction) depending on the RPC
    # encoding path, so normalize both shapes here.
    import base58 as _bs58

    memo_program_id = Pubkey.from_string(
        "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
    )
    found_memo = False
    for ix in message.instructions:
        program_idx = ix.program_id_index
        if program_idx >= len(account_keys):
            continue
        if account_keys[program_idx] != memo_program_id:
            continue
        raw = ix.data
        if isinstance(raw, str):
            try:
                raw_bytes = _bs58.b58decode(raw)
            except Exception:
                continue
        elif isinstance(raw, (bytes, bytearray)):
            raw_bytes = bytes(raw)
        else:
            continue
        try:
            memo_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if memo_text == expected_memo:
            found_memo = True
            break
    if not found_memo:
        raise SolanaClientError(
            "payment tx memo does not match expected binding "
            f"(expected memo={expected_memo!r})"
        )


async def verify_attestation_pda(case_id: bytes) -> str | None:
    """Return the attestation PDA address iff it exists on devnet.

    Used by the confirm endpoint: if the PDA was initialized by our
    program, then a valid create_case_attestation tx was executed for
    ``case_id`` - that is sufficient proof for the backend to persist the
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

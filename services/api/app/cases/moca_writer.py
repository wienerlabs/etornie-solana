"""Moca-chain attestation writer (#73 full integration).

When a case is routed to Moca (``moca`` or ``both``) and the integration
is enabled, the Etornie operator records an attestation on the Moca
chain by calling ``EtornieAttestation.attest(caseId, dataHash)``:

* ``caseId``  = keccak256(case UUID)
* ``dataHash`` = keccak256 of the case's canonical data

web3 is synchronous, so the actual transaction runs in a worker thread
and the result is persisted from an async background task that owns its
own DB session (mirrors the Solana NFT-setup background pattern).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from web3 import Web3

from app.cases.models import Case, MocaStatus
from app.config import settings

logger = logging.getLogger(__name__)

# Minimal ABI matching contracts/moca/EtornieAttestation.sol.
ATTESTATION_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "caseId", "type": "bytes32"},
            {"internalType": "bytes32", "name": "dataHash", "type": "bytes32"},
        ],
        "name": "attest",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "caseId", "type": "bytes32"}
        ],
        "name": "getAttestation",
        "outputs": [
            {"internalType": "bytes32", "name": "dataHash", "type": "bytes32"},
            {"internalType": "address", "name": "attester", "type": "address"},
            {"internalType": "uint64", "name": "timestamp", "type": "uint64"},
            {"internalType": "bool", "name": "exists", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


class MocaWriteError(RuntimeError):
    """Raised when the Moca attestation transaction cannot be sent."""


def is_configured() -> bool:
    """True when Moca writes are enabled and fully configured."""

    return bool(
        settings.moca_enabled
        and settings.moca_operator_private_key
        and settings.moca_attestation_contract
    )


def case_id_bytes32(case_uuid: uuid.UUID) -> bytes:
    return Web3.keccak(text=str(case_uuid))


def case_data_hash(case: Case) -> bytes:
    """keccak256 over the case's canonical, stable data fields."""

    canonical = "|".join(
        [
            "etornie-case-v1",
            str(case.id),
            case.case_number or "",
            case.title or "",
            case.case_type.value if case.case_type else "",
            case.jurisdiction or "",
            case.nice_classes or "",
        ]
    )
    return Web3.keccak(text=canonical)


def _send_attestation_sync(case_uuid: uuid.UUID, data_hash: bytes) -> str:
    """Build, sign, and send the attest() tx. Returns the tx hash hex.

    Runs synchronously (web3 is blocking); call it via a worker thread.
    """
    w3 = Web3(Web3.HTTPProvider(settings.moca_rpc_url, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        raise MocaWriteError(f"cannot reach Moca RPC {settings.moca_rpc_url}")

    account = w3.eth.account.from_key(settings.moca_operator_private_key)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(settings.moca_attestation_contract),
        abi=ATTESTATION_ABI,
    )

    case_id = case_id_bytes32(case_uuid)
    func = contract.functions.attest(case_id, data_hash)

    tx = func.build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": settings.moca_chain_id,
            "gas": 200_000,
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise MocaWriteError(f"Moca tx reverted: {tx_hash.hex()}")
    return tx_hash.hex()


async def attest_case(case: Case) -> str:
    """Send the Moca attestation for ``case`` and return the tx hash."""

    if not is_configured():
        raise MocaWriteError("Moca integration is not configured/enabled")
    data_hash = case_data_hash(case)
    return await asyncio.to_thread(_send_attestation_sync, case.id, data_hash)


async def trigger_moca_attestation_background(case_id: uuid.UUID) -> None:
    """Background task: write the Moca attestation and persist the result.

    Opens its own DB session so it can run after the request's session has
    closed. Best-effort: failures flip the case to ``moca_status=failed``
    rather than raising into the caller.
    """
    from sqlalchemy import select

    from app.database import async_session

    async with async_session() as db:
        # The request that scheduled us may not have committed the case
        # row yet (FastAPI runs background tasks around the get_db commit).
        # Poll briefly — awaiting yields the loop so that commit can land.
        case = None
        for _ in range(15):
            case = (
                await db.execute(select(Case).where(Case.id == case_id))
            ).scalar_one_or_none()
            if case is not None:
                break
            await asyncio.sleep(1)
        if case is None:
            logger.warning("Moca attest: case %s not found", case_id)
            return
        try:
            tx_hash = await attest_case(case)
        except Exception as exc:  # noqa: BLE001 — best-effort background write
            logger.warning("Moca attestation failed for case %s: %s", case_id, exc)
            case.moca_status = MocaStatus.failed
            await db.commit()
            return

        tx_hex = tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}"
        case.moca_attestation_tx = tx_hex
        case.moca_status = MocaStatus.written
        await db.commit()
        logger.info(
            "Moca attestation written for case %s: %s", case_id, tx_hex
        )

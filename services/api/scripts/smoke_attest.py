"""Smoke test: submit a fake create_case_attestation from Python directly.

Run from services/api/ with the venv active:

    .venv/bin/python scripts/smoke_attest.py
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid

from solders.keypair import Keypair


async def main() -> None:
    from app.solana.client import (
        canonicalize_metadata,
        create_case_attestation,
        derive_attestation_pda,
    )

    case_id = uuid.uuid4()
    case_id_bytes = case_id.bytes
    metadata_hash = canonicalize_metadata(
        {
            "case_id": str(case_id),
            "case_number": "ETR-TEST-0001",
            "title": "Smoke Test Trademark",
            "case_type": "trademark",
        }
    )
    creator = Keypair().pubkey()  # random throwaway creator
    client_wallet = Keypair().pubkey()  # random throwaway client

    pda, bump = derive_attestation_pda(case_id_bytes)
    print(f"case_id:       {case_id}")
    print(f"case_id_hex:   {case_id_bytes.hex()}")
    print(f"metadata_hash: {metadata_hash.hex()}")
    print(f"creator:       {creator}")
    print(f"client_wallet: {client_wallet}")
    print(f"pda:           {pda}  (bump {bump})")

    tx_sig, pda_str = await create_case_attestation(
        case_id=case_id_bytes,
        metadata_hash=metadata_hash,
        creator=creator,
        client_wallet=client_wallet,
    )
    print(f"\n[OK] tx:  https://explorer.solana.com/tx/{tx_sig}?cluster=devnet")
    print(f"     pda: https://explorer.solana.com/address/{pda_str}?cluster=devnet")


if __name__ == "__main__":
    asyncio.run(main())

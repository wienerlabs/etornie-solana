"""ZK Lab sponsored verify_proof endpoints.

Flow:
  1. POST /zk/verify-prepare
       Client passes the already-converted on-chain proof bytes and the
       journal digest. We return the program id, account metas (PDA +
       signer slots), base64 ix data, and a fresh blockhash.
  2. Frontend assembles a VersionedTransaction (fee_payer = backend
     operator, user = Phantom wallet), has Phantom sign slot 1, and
     ships the fully-serialised (but partially-signed) tx to step 3.
  3. POST /zk/verify-submit
       Backend splices its operator signature into slot 0 without
       re-serialising the message, then submits to devnet and returns
       the confirmed signature.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from solders.pubkey import Pubkey

from app.config import settings
from app.solana.client import (
    SolanaClientError,
    build_verify_proof_ix_payload,
    derive_proof_record_pda,
    finalize_sponsored_verify_tx,
)

router = APIRouter(prefix="/zk", tags=["zk-verifier"])


class VerifyPrepareRequest(BaseModel):
    user_wallet: str = Field(..., description="User Solana pubkey (base58)")
    proof_a_b64: str = Field(..., description="64-byte proof_a, base64")
    proof_b_b64: str = Field(..., description="128-byte proof_b, base64")
    proof_c_b64: str = Field(..., description="64-byte proof_c, base64")
    public_inputs_b64: list[str] = Field(
        ...,
        description="Each entry is a 32-byte big-endian public input, base64",
    )
    journal_digest_b64: str = Field(
        ..., description="sha256(concat(public_inputs)), 32 bytes, base64"
    )


class VerifyPrepareResponse(BaseModel):
    program_id: str
    fee_payer: str
    user: str
    proof_record: str
    ix_data_b64: str
    recent_blockhash: str


class VerifySubmitRequest(BaseModel):
    signed_tx_b64: str = Field(
        ...,
        description=(
            "User-signed VersionedTransaction bytes, base64. Fee-payer "
            "slot (index 0) is left zeroed; backend fills it in."
        ),
    )


class VerifySubmitResponse(BaseModel):
    signature: str
    explorer_url: str


def _ensure_enabled() -> None:
    if not settings.solana_zk_verifier_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "zk verifier endpoint disabled by config",
        )


def _b64_decode(field_name: str, value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid base64 for {field_name}: {exc}",
        ) from exc


@router.post("/verify-prepare", response_model=VerifyPrepareResponse)
async def verify_prepare(req: VerifyPrepareRequest) -> VerifyPrepareResponse:
    _ensure_enabled()

    try:
        user = Pubkey.from_string(req.user_wallet)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid user_wallet: {exc}"
        ) from exc

    proof_a = _b64_decode("proof_a_b64", req.proof_a_b64)
    proof_b = _b64_decode("proof_b_b64", req.proof_b_b64)
    proof_c = _b64_decode("proof_c_b64", req.proof_c_b64)
    public_inputs = [
        _b64_decode(f"public_inputs_b64[{i}]", x)
        for i, x in enumerate(req.public_inputs_b64)
    ]
    journal_digest = _b64_decode("journal_digest_b64", req.journal_digest_b64)

    try:
        payload = await build_verify_proof_ix_payload(
            user=user,
            proof_a=proof_a,
            proof_b=proof_b,
            proof_c=proof_c,
            public_inputs=public_inputs,
            journal_digest=journal_digest,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except SolanaClientError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"solana rpc error: {exc}"
        ) from exc

    data: dict[str, Any] = asdict(payload)
    return VerifyPrepareResponse(**data)


@router.post("/verify-submit", response_model=VerifySubmitResponse)
async def verify_submit(req: VerifySubmitRequest) -> VerifySubmitResponse:
    _ensure_enabled()

    signed_tx = _b64_decode("signed_tx_b64", req.signed_tx_b64)

    try:
        signature = await finalize_sponsored_verify_tx(signed_tx)
    except SolanaClientError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return VerifySubmitResponse(
        signature=signature,
        explorer_url=(
            f"https://explorer.solana.com/tx/{signature}?cluster=devnet"
        ),
    )


@router.get("/proof-record/{user_wallet}/{journal_digest_hex}")
async def get_proof_record_pda(
    user_wallet: str, journal_digest_hex: str
) -> dict[str, str]:
    """Derive the ProofRecord PDA for (user, digest) without touching RPC.

    Useful for the frontend to display the PDA before submitting, or to
    link to the explorer immediately after a successful verify-submit.
    """
    _ensure_enabled()
    try:
        user = Pubkey.from_string(user_wallet)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid user_wallet: {exc}"
        ) from exc
    try:
        digest = bytes.fromhex(journal_digest_hex)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"journal_digest_hex is not hex: {exc}",
        ) from exc
    if len(digest) != 32:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"journal_digest must be 32 bytes, got {len(digest)}",
        )

    pda, bump = derive_proof_record_pda(user, digest)
    return {
        "proof_record": str(pda),
        "bump": str(bump),
        "explorer_url": (
            f"https://explorer.solana.com/address/{pda}?cluster=devnet"
        ),
    }

"""EtornieGPT endpoints: legacy free endpoint + x402-gated chat flow.

Faz 5.6 adds:
  * GET  /etorniegpt/chat/payment-requirements
        x402-style advertisement of the devnet SOL micropayment the
        frontend must produce (recipient, lamports, memo scheme).
  * POST /etorniegpt/chat
        Accepts the user's query *together with* proof of payment:
          - `payment_tx`             : signature of an already-confirmed
                                       devnet SOL transfer to the vault
                                       whose memo binds to the query.
          - `compliance_proof`       : Groth16 proof that the payer
                                       controls the secret underpinning
                                       the memo commitment.
        Backend verifies both, submits the compliance tx via the
        operator (sponsored), forwards to Together AI, and persists the
        exchange in `chat_messages`.
  * GET  /etorniegpt/chat/history
        Returns the authenticated user's paid chat history in reverse
        chronological order.
"""
from __future__ import annotations

import base58
import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from solders.pubkey import Pubkey

from app.auth.dependencies import get_current_user
from app.braid.audit import record_decision_async
from app.config import settings
from app.database import get_db
from app.etorniegpt.countries import get_all_countries
from app.etorniegpt.models import ChatMessage
from app.etorniegpt.schemas import (
    ChatMessageOut,
    EtornieGPTChatRequest,
    EtornieGPTChatResponse,
    EtornieGPTRequest,
    EtornieGPTResponse,
    PaymentRequirementsResponse,
)
from app.etorniegpt.service import ask_etorniegpt
from app.solana.client import (
    SolanaClientError,
    derive_compliance_record_pda,
    submit_compliance_proof_tx,
    verify_payment_tx,
)
from app.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["etorniegpt"])


@router.get("/countries")
async def list_countries(
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Return list of countries with name and code for dropdowns."""
    countries = get_all_countries()
    return [
        {"country": c.get("country", ""), "country_code": c.get("country_code")}
        for c in countries
        if c.get("country")
    ]


@router.post("/etorniegpt", response_model=EtornieGPTResponse)
async def etorniegpt_endpoint(
    data: EtornieGPTRequest,
    current_user: User = Depends(get_current_user),
) -> EtornieGPTResponse:
    """Legacy free endpoint - kept for admin/internal flows. UI uses /chat."""
    try:
        result = await ask_etorniegpt(
            question=data.question,
            language=data.language,
        )
        return EtornieGPTResponse(**result)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"EtornieGPT service error: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# x402 payment-gated chat (Faz 5.6)
# ---------------------------------------------------------------------------


def _ensure_x402_enabled() -> None:
    if not settings.etorniegpt_payment_vault:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "etorniegpt x402 flow not configured (missing vault)",
        )


@router.get(
    "/etorniegpt/chat/payment-requirements",
    response_model=PaymentRequirementsResponse,
)
async def chat_payment_requirements(
    current_user: User = Depends(get_current_user),
) -> PaymentRequirementsResponse:
    """Advertise the payment requirements for a single query.

    Mirrors the data that would ship in an HTTP 402 response body - the
    frontend reads this once at page load and uses it to build the
    payment tx for every query in the session.
    """
    _ensure_x402_enabled()
    return PaymentRequirementsResponse(
        recipient=settings.etorniegpt_payment_vault,
        lamports=settings.etorniegpt_payment_lamports,
    )


def _b64_decode_strict(field_name: str, value: str, expected_len: int | None = None) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid base64 for {field_name}: {exc}",
        ) from exc
    if expected_len is not None and len(raw) != expected_len:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{field_name}: expected {expected_len} bytes, got {len(raw)}",
        )
    return raw


def _compute_expected_memo(query_hash: bytes, commitment: bytes) -> str:
    """Memo scheme: base58(sha256(query_hash || commitment))."""
    digest = hashlib.sha256(query_hash + commitment).digest()
    return base58.b58encode(digest).decode("ascii")


@router.post(
    "/etorniegpt/chat",
    response_model=EtornieGPTChatResponse,
    responses={
        402: {"description": "Payment required (x402 handshake)"},
    },
)
async def etorniegpt_chat(
    data: EtornieGPTChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> EtornieGPTChatResponse:
    """Ask EtornieGPT a question, gated by an on-chain SOL micropayment
    and a ZK compliance proof.

    Flow:
      1. Decode and sanity-check the submitted proof.
      2. Verify the question's sha256 matches the `query_hash` public input.
      3. Derive the expected payment memo = base58(sha256(qh||commitment))
         and verify the on-chain payment tx carries that exact memo to
         the configured vault with at least the configured lamports.
      4. Submit the verify_compliance_proof tx (operator signs alone).
      5. Call Together AI with the question.
      6. Persist the exchange in chat_messages.
    """
    _ensure_x402_enabled()
    logger.info(
        "etorniegpt chat: user=%s payer=%s payment_tx=%s",
        current_user.id,
        data.payer_wallet,
        data.payment_tx,
    )

    # ---- parse proof bytes ------------------------------------------------
    proof_a = _b64_decode_strict(
        "compliance_proof.proof_a_b64", data.compliance_proof.proof_a_b64, 64
    )
    proof_b = _b64_decode_strict(
        "compliance_proof.proof_b_b64", data.compliance_proof.proof_b_b64, 128
    )
    proof_c = _b64_decode_strict(
        "compliance_proof.proof_c_b64", data.compliance_proof.proof_c_b64, 64
    )
    if len(data.compliance_proof.public_inputs_b64) != 3:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "compliance_proof.public_inputs_b64 must have exactly 3 entries "
            "[qh_hi, qh_lo, commitment]",
        )
    public_inputs = [
        _b64_decode_strict(
            f"compliance_proof.public_inputs_b64[{i}]", v, 32
        )
        for i, v in enumerate(data.compliance_proof.public_inputs_b64)
    ]
    query_hash = _b64_decode_strict(
        "compliance_proof.query_hash_b64",
        data.compliance_proof.query_hash_b64,
        32,
    )

    # ---- cryptographic binding checks -------------------------------------
    expected_qh = hashlib.sha256(data.question.encode("utf-8")).digest()
    if expected_qh != query_hash:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "query_hash does not match sha256(question) - "
            "client must hash the exact question text being sent",
        )

    # Canonical halves pinning is enforced on-chain too, but we want a
    # fast 400 before paying the pairing CU cost if the client sent a
    # malformed payload.
    expected_qh_hi = b"\x00" * 16 + query_hash[:16]
    expected_qh_lo = b"\x00" * 16 + query_hash[16:]
    if public_inputs[0] != expected_qh_hi or public_inputs[1] != expected_qh_lo:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "public_inputs[0]/[1] do not match canonical zero-padded "
            "halves of query_hash",
        )

    commitment = public_inputs[2]

    # ---- verify payment tx ------------------------------------------------
    try:
        payer = Pubkey.from_string(data.payer_wallet)
        vault = Pubkey.from_string(settings.etorniegpt_payment_vault)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid pubkey: {exc}"
        ) from exc

    expected_memo = _compute_expected_memo(query_hash, commitment)
    audit_args = {
        "signature": data.payment_tx,
        "expected_memo": expected_memo,
        "min_lamports": settings.etorniegpt_payment_lamports,
        "recipient_vault": str(vault),
    }
    audit_started = datetime.now(timezone.utc)
    audit_failure: str | None = None
    audit_crash: str | None = None
    try:
        await verify_payment_tx(
            signature=data.payment_tx,
            expected_recipient=vault,
            min_lamports=settings.etorniegpt_payment_lamports,
            expected_memo=expected_memo,
        )
    except SolanaClientError as exc:
        audit_failure = str(exc)
        logger.warning("etorniegpt payment verify failed: %s", exc)
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, f"payment verification failed: {exc}"
        ) from exc
    except Exception as exc:
        audit_crash = str(exc)
        logger.exception("etorniegpt payment verify crashed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"payment verify crashed: {exc}",
        ) from exc
    finally:
        audit_completed = datetime.now(timezone.utc)
        if audit_crash is not None:
            audit_result = None
            audit_error: str | None = audit_crash
        elif audit_failure is not None:
            audit_result = {
                "verified": False,
                "signature": data.payment_tx,
                "recipient_vault": str(vault),
                "min_lamports_required": settings.etorniegpt_payment_lamports,
                "expected_memo": expected_memo,
                "error": audit_failure,
            }
            audit_error = None
        else:
            audit_result = {
                "verified": True,
                "signature": data.payment_tx,
                "recipient_vault": str(vault),
                "min_lamports_required": settings.etorniegpt_payment_lamports,
                "expected_memo": expected_memo,
            }
            audit_error = None
        record_decision_async(
            workspace_id=f"etorniegpt:{current_user.id}",
            capability_name="verify_x402_payment",
            args=audit_args,
            result=audit_result,
            error=audit_error,
            user_message=f"EtornieGPT query: {data.question[:200]}",
            started_at=audit_started,
            completed_at=audit_completed,
            agent_name="etorniegpt-direct",
        )

    # ---- duplicate-query short-circuit -----------------------------------
    # If this wallet already has a ComplianceRecord for this exact query,
    # the verifier program will reject the proof with ReplayedProof (6003).
    # Reuse the cached answer so the user never pays twice for the same
    # question + wallet pair.
    query_hash_hex = query_hash.hex()
    existing_stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.payer_wallet == str(payer),
            ChatMessage.query_hash_hex == query_hash_hex,
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(1)
    )
    existing_row = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing_row is not None:
        logger.info(
            "etorniegpt chat: cached hit user=%s query_hash=%s",
            current_user.id,
            query_hash_hex,
        )
        cluster = "devnet"
        compliance_tx = existing_row.compliance_tx or ""
        compliance_pda = existing_row.compliance_pda or ""
        return EtornieGPTChatResponse(
            answer=existing_row.answer,
            country_detected=existing_row.country_detected,
            model=existing_row.model,
            query_hash_hex=query_hash_hex,
            commitment_hex=existing_row.commitment_hex or commitment.hex(),
            payment_tx=data.payment_tx,
            compliance_tx=compliance_tx,
            compliance_pda=compliance_pda,
            payment_explorer_url=(
                f"https://explorer.solana.com/tx/{data.payment_tx}?cluster={cluster}"
            ),
            compliance_explorer_url=(
                f"https://explorer.solana.com/tx/{compliance_tx}?cluster={cluster}"
                if compliance_tx
                else ""
            ),
            compliance_record_explorer_url=(
                f"https://explorer.solana.com/address/{compliance_pda}?cluster={cluster}"
                if compliance_pda
                else ""
            ),
        )

    # ---- submit compliance proof on-chain ---------------------------------
    try:
        compliance_tx, compliance_pda = await submit_compliance_proof_tx(
            user=payer,
            proof_a=proof_a,
            proof_b=proof_b,
            proof_c=proof_c,
            public_inputs=public_inputs,
            query_hash=query_hash,
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except SolanaClientError as exc:
        logger.error("etorniegpt compliance submit failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"compliance proof submission failed: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("etorniegpt compliance submit crashed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"compliance submit crashed: {exc}",
        ) from exc

    # ---- forward to LLM ---------------------------------------------------
    try:
        result = await ask_etorniegpt(
            question=data.question, language=data.language
        )
    except Exception as exc:
        logger.error("etorniegpt LLM call failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"EtornieGPT service error: {exc}",
        ) from exc

    # ---- persist chat message --------------------------------------------
    record = ChatMessage(
        user_id=current_user.id,
        question=data.question,
        answer=result["answer"],
        model=result["model"],
        country_detected=result.get("country_detected"),
        language=data.language,
        query_hash_hex=query_hash.hex(),
        commitment_hex=commitment.hex(),
        payer_wallet=str(payer),
        payment_tx=data.payment_tx,
        compliance_tx=compliance_tx,
        compliance_pda=str(compliance_pda),
    )
    db.add(record)
    await db.flush()

    cluster = "devnet"
    return EtornieGPTChatResponse(
        answer=result["answer"],
        country_detected=result.get("country_detected"),
        model=result["model"],
        query_hash_hex=query_hash.hex(),
        commitment_hex=commitment.hex(),
        payment_tx=data.payment_tx,
        compliance_tx=compliance_tx,
        compliance_pda=str(compliance_pda),
        payment_explorer_url=f"https://explorer.solana.com/tx/{data.payment_tx}?cluster={cluster}",
        compliance_explorer_url=f"https://explorer.solana.com/tx/{compliance_tx}?cluster={cluster}",
        compliance_record_explorer_url=(
            f"https://explorer.solana.com/address/{compliance_pda}?cluster={cluster}"
        ),
    )


@router.get("/etorniegpt/chat/cache-lookup")
async def etorniegpt_cache_lookup(
    payer_wallet: str,
    query_hash_hex: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Check whether a (payer_wallet, query_hash) tuple already has a
    recorded answer. Frontends call this before asking the user to sign a
    payment tx, so duplicate queries skip the wallet popup entirely and
    just re-render the cached response.

    Response shape:
      {"cached": false}
      {"cached": true, "answer": str, "model": str, "country_detected":
       str|null, "compliance_tx": str|null, "compliance_pda": str|null,
       "payment_tx": str|null, ...explorer_urls}
    """
    _ensure_x402_enabled()
    if len(query_hash_hex) != 64:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "query_hash_hex must be 64 hex chars (32 bytes)",
        )
    # Defensive: reject non-hex early to keep the log clean.
    try:
        bytes.fromhex(query_hash_hex)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"query_hash_hex not hex: {exc}"
        ) from exc

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.payer_wallet == payer_wallet,
            ChatMessage.query_hash_hex == query_hash_hex,
            ChatMessage.user_id == current_user.id,
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return {"cached": False}
    cluster = "devnet"
    return {
        "cached": True,
        "answer": row.answer,
        "model": row.model,
        "country_detected": row.country_detected,
        "payment_tx": row.payment_tx,
        "compliance_tx": row.compliance_tx,
        "compliance_pda": row.compliance_pda,
        "payment_explorer_url": (
            f"https://explorer.solana.com/tx/{row.payment_tx}?cluster={cluster}"
            if row.payment_tx
            else None
        ),
        "compliance_explorer_url": (
            f"https://explorer.solana.com/tx/{row.compliance_tx}?cluster={cluster}"
            if row.compliance_tx
            else None
        ),
        "compliance_record_explorer_url": (
            f"https://explorer.solana.com/address/{row.compliance_pda}?cluster={cluster}"
            if row.compliance_pda
            else None
        ),
    }


@router.get("/etorniegpt/chat/history", response_model=list[ChatMessageOut])
async def etorniegpt_chat_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
    limit: int = 50,
) -> list[ChatMessageOut]:
    """Return the authenticated user's paid chat history, newest first."""
    limit = max(1, min(limit, 200))
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        ChatMessageOut(
            id=str(r.id),
            question=r.question,
            answer=r.answer,
            model=r.model,
            country_detected=r.country_detected,
            language=r.language,
            query_hash_hex=r.query_hash_hex,
            payment_tx=r.payment_tx,
            compliance_tx=r.compliance_tx,
            compliance_pda=r.compliance_pda,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/etorniegpt/chat/compliance-record/{payer_wallet}/{query_hash_hex}")
async def get_compliance_record_pda(
    payer_wallet: str,
    query_hash_hex: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Derive the ComplianceRecord PDA for (payer, query_hash), no RPC.

    Frontend uses this to render the explorer link before waiting for the
    verify_compliance_proof tx to confirm.
    """
    _ensure_x402_enabled()
    try:
        user = Pubkey.from_string(payer_wallet)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid payer_wallet: {exc}"
        ) from exc
    try:
        query_hash = bytes.fromhex(query_hash_hex)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"query_hash_hex is not hex: {exc}",
        ) from exc
    if len(query_hash) != 32:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"query_hash must be 32 bytes, got {len(query_hash)}",
        )
    pda, bump = derive_compliance_record_pda(user, query_hash)
    return {
        "compliance_record": str(pda),
        "bump": str(bump),
        "explorer_url": (
            f"https://explorer.solana.com/address/{pda}?cluster=devnet"
        ),
    }

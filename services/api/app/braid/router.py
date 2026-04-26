"""BRAID-internal endpoints.

Thin reasoning-side endpoints consumed by the OpenServ BRAID agent in
``services/braid``. These wrap canonical Etornie logic (e.g. on-chain
payment verification) so the agent does not duplicate domain code.

Auth: every endpoint requires an ``X-Braid-Auth`` header that matches
``settings.braid_internal_token``. If the token is unset, the entire
router refuses requests (fail-closed). The token is shared between this
service and ``services/braid/.env``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from solders.pubkey import Pubkey
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.braid.models import BraidDecision
from app.config import settings
from app.database import get_db
from app.solana.client import SolanaClientError, verify_payment_tx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/braid", tags=["braid"])


def _check_auth(x_braid_auth: str | None) -> None:
    if not settings.braid_internal_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "braid endpoints disabled (BRAID_INTERNAL_TOKEN unset)",
        )
    if x_braid_auth != settings.braid_internal_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing X-Braid-Auth header",
        )


class VerifyX402Request(BaseModel):
    signature: str = Field(
        ..., description="Solana transaction signature of the payment to verify"
    )
    expected_memo: str = Field(
        ...,
        description=(
            "Memo string the payment must carry; typically "
            "base58(sha256(query_hash || commitment))"
        ),
    )
    min_lamports: int | None = Field(
        default=None,
        description="Override min lamports; defaults to platform setting",
    )
    recipient_vault: str | None = Field(
        default=None,
        description="Override recipient vault pubkey; defaults to platform setting",
    )


class VerifyX402Response(BaseModel):
    verified: bool
    signature: str
    recipient_vault: str
    min_lamports_required: int
    expected_memo: str
    error: str | None = None


@router.post(
    "/verify-x402-payment",
    response_model=VerifyX402Response,
    summary="Verify an x402 SOL micropayment for the EtornieGPT flow",
)
async def verify_x402_payment(
    body: VerifyX402Request,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> VerifyX402Response:
    """Verify a Solana payment tx against the EtornieGPT vault.

    Always returns ``HTTP 200`` so the BRAID agent can reason over the
    structured outcome (success or auditable failure). Auth/config errors
    use proper HTTP status codes.
    """
    _check_auth(x_braid_auth)

    vault_str = body.recipient_vault or settings.etorniegpt_payment_vault
    if not vault_str:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "etorniegpt payment vault not configured",
        )

    min_lamports = body.min_lamports or settings.etorniegpt_payment_lamports

    try:
        recipient = Pubkey.from_string(vault_str)
    except Exception as exc:  # noqa: BLE001 - normalize all parse errors
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid recipient_vault pubkey: {exc}",
        ) from exc

    try:
        await verify_payment_tx(
            signature=body.signature,
            expected_recipient=recipient,
            min_lamports=min_lamports,
            expected_memo=body.expected_memo,
        )
    except SolanaClientError as exc:
        logger.info(
            "braid verify_x402 failed sig=%s reason=%s", body.signature, exc
        )
        return VerifyX402Response(
            verified=False,
            signature=body.signature,
            recipient_vault=vault_str,
            min_lamports_required=min_lamports,
            expected_memo=body.expected_memo,
            error=str(exc),
        )

    return VerifyX402Response(
        verified=True,
        signature=body.signature,
        recipient_vault=vault_str,
        min_lamports_required=min_lamports,
        expected_memo=body.expected_memo,
    )


# ────────────────────────────────────────────────────────────────────
# Audit trail — BRAID decisions
# ────────────────────────────────────────────────────────────────────


class CreateDecisionRequest(BaseModel):
    workspace_id: str = Field(..., max_length=64)
    thread_id: int
    agent_id: int
    agent_name: str | None = Field(default=None, max_length=128)
    capability_name: str = Field(..., max_length=128)
    args: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    user_message: str | None = None
    started_at: datetime
    completed_at: datetime
    duration_ms: int


class DecisionRow(BaseModel):
    id: uuid.UUID
    workspace_id: str
    thread_id: int
    agent_id: int
    agent_name: str | None
    capability_name: str
    args: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    user_message: str | None
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionList(BaseModel):
    items: list[DecisionRow]
    count: int


def _row_to_model(row: BraidDecision) -> DecisionRow:
    return DecisionRow.model_validate(row)


@router.post(
    "/decisions",
    response_model=DecisionRow,
    status_code=status.HTTP_201_CREATED,
    summary="Record a BRAID capability invocation (audit trail write)",
)
async def create_decision(
    body: CreateDecisionRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionRow:
    """Persist one capability invocation. Called by the BRAID agent
    after every wrapped capability finishes, fire-and-forget."""
    _check_auth(x_braid_auth)

    decision = BraidDecision(
        workspace_id=body.workspace_id,
        thread_id=body.thread_id,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        capability_name=body.capability_name,
        args=body.args,
        result=body.result,
        error=body.error,
        user_message=body.user_message,
        started_at=body.started_at,
        completed_at=body.completed_at,
        duration_ms=body.duration_ms,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)
    return _row_to_model(decision)


@router.get(
    "/decisions",
    response_model=DecisionList,
    summary="List BRAID decisions (newest first); filter by workspace, thread, capability",
)
async def list_decisions(
    workspace_id: str | None = Query(default=None, max_length=64),
    thread_id: int | None = Query(default=None),
    capability_name: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=500),
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    _check_auth(x_braid_auth)

    stmt = select(BraidDecision).order_by(desc(BraidDecision.started_at))
    if workspace_id is not None:
        stmt = stmt.where(BraidDecision.workspace_id == workspace_id)
    if thread_id is not None:
        stmt = stmt.where(BraidDecision.thread_id == thread_id)
    if capability_name is not None:
        stmt = stmt.where(BraidDecision.capability_name == capability_name)
    stmt = stmt.limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return DecisionList(
        items=[_row_to_model(r) for r in rows], count=len(rows)
    )


@router.get(
    "/decisions/trace",
    response_model=DecisionList,
    summary="Chronological trace of decisions for one (workspace, thread)",
)
async def get_trace(
    workspace_id: str = Query(..., max_length=64),
    thread_id: int = Query(...),
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    """Returns the ordered (oldest → newest) chain of BRAID capability
    calls within a single chat thread. This is the reasoning trace a
    regulator/auditor reads to reconstruct how a decision was reached."""
    _check_auth(x_braid_auth)

    stmt = (
        select(BraidDecision)
        .where(BraidDecision.workspace_id == workspace_id)
        .where(BraidDecision.thread_id == thread_id)
        .order_by(BraidDecision.started_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return DecisionList(
        items=[_row_to_model(r) for r in rows], count=len(rows)
    )


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionRow,
    summary="Single decision detail",
)
async def get_decision(
    decision_id: uuid.UUID,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionRow:
    _check_auth(x_braid_auth)

    row = await db.get(BraidDecision, decision_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"decision {decision_id} not found"
        )
    return _row_to_model(row)

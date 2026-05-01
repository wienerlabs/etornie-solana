"""HTTP API for the agent orchestrator."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import service
from app.agent.orchestrator import OrchestratorError, run_turn
from app.agent.schemas import (
    MessageListResponse,
    MessageSendRequest,
    SessionCreateRequest,
    SessionListResponse,
    SessionRenameRequest,
    SessionResponse,
    TurnResponse,
)
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.users.models import User

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionListResponse:
    sessions = await service.list_sessions(db, user_id=current_user.id)
    return SessionListResponse(
        sessions=[SessionResponse.model_validate(s) for s in sessions]
    )


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session_endpoint(
    data: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    session = await service.create_session(
        db, user_id=current_user.id, title=data.title
    )
    return SessionResponse.model_validate(session)


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def rename_session_endpoint(
    session_id: uuid.UUID,
    data: SessionRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    session = await service.get_session_for_user(
        db, session_id=session_id, user_id=current_user.id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await service.rename_session(db, session=session, title=data.title)
    return SessionResponse.model_validate(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session_endpoint(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    session = await service.get_session_for_user(
        db, session_id=session_id, user_id=current_user.id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await service.soft_delete_session(db, session=session)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=MessageListResponse,
)
async def list_messages_endpoint(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageListResponse:
    session = await service.get_session_for_user(
        db, session_id=session_id, user_id=current_user.id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await service.list_messages(db, session_id=session_id)
    return MessageListResponse(messages=[m for m in messages])  # pydantic from_attributes


@router.get("/filings/{submission_id}/payment-requirements")
async def filing_payment_requirements_endpoint(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return everything the wallet needs to build a Solana payment tx.

    Phase 0 wires a flat-rate SOL transfer to the platform vault with a
    memo bound to the submission id. The real x402 USDC handshake will
    replace this once the off-ramp is in place; the wire shape stays
    the same so the frontend Pay button does not need to change.
    """
    from app.cases.models import Case
    from app.config import settings
    from app.services.ukipo.models import (
        UKIPOSubmission,
        UKIPOSubmissionStatus,
    )

    result = await db.execute(
        select(UKIPOSubmission).where(UKIPOSubmission.id == submission_id)
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    case_result = await db.execute(
        select(Case).where(Case.id == submission.case_id)
    )
    case = case_result.scalar_one_or_none()
    if case is None or (
        case.client_id != current_user.id
        and current_user.role.value != "admin"
    ):
        raise HTTPException(status_code=404, detail="Submission not found")

    if submission.status != UKIPOSubmissionStatus.awaiting_payment:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Submission is in status '{submission.status.value}'; "
                "payment can only be initiated once the robot reaches "
                "awaiting_payment."
            ),
        )

    vault = (
        getattr(settings, "ukipo_payment_vault", "")
        or getattr(settings, "etorniegpt_payment_vault", "")
    )
    if not vault:
        raise HTTPException(
            status_code=500,
            detail=(
                "Payment vault address is not configured "
                "(UKIPO_PAYMENT_VAULT or ETORNIEGPT_PAYMENT_VAULT)."
            ),
        )

    # Flat 0.01 SOL placeholder fee. The actual GBP-equivalent USDC
    # quote arrives with the x402 integration; for Phase 0 we only need
    # a real, signable tx so the on-chain plumbing is exercised.
    lamports = 10_000_000

    return {
        "submission_id": str(submission.id),
        "vault": vault,
        "lamports": lamports,
        "memo": f"etornie-ukipo:{submission.id}",
        "currency": "SOL",
        "network": "solana-devnet",
        "platform_fee_gbp": 265,
    }


@router.post("/filings/{submission_id}/confirm-payment")
async def filing_confirm_payment_endpoint(
    submission_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Record a Solana payment tx hash against a UKIPOSubmission.

    The frontend submits the signed-and-confirmed transaction signature
    here. Phase 0 simply persists it; later phases will verify the tx
    on-chain (lamports, memo, recipient) before flipping submission
    status to 'filed'.
    """
    from datetime import datetime, timezone

    from app.cases.models import Case
    from app.services.ukipo.models import UKIPOSubmission

    tx = (payload or {}).get("tx_signature")
    payer = (payload or {}).get("payer_wallet")
    lamports = (payload or {}).get("lamports")
    if not isinstance(tx, str) or not tx.strip():
        raise HTTPException(status_code=422, detail="tx_signature is required")

    result = await db.execute(
        select(UKIPOSubmission).where(UKIPOSubmission.id == submission_id)
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    case_result = await db.execute(
        select(Case).where(Case.id == submission.case_id)
    )
    case = case_result.scalar_one_or_none()
    if case is None or (
        case.client_id != current_user.id
        and current_user.role.value != "admin"
    ):
        raise HTTPException(status_code=404, detail="Submission not found")

    submission.solana_payment_tx = tx.strip()
    if isinstance(payer, str) and payer.strip():
        submission.solana_payer_wallet = payer.strip()
    if isinstance(lamports, int):
        submission.solana_payment_lamports = lamports
    submission.solana_payment_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "submission_id": str(submission.id),
        "tx_signature": submission.solana_payment_tx,
        "payer_wallet": submission.solana_payer_wallet,
        "lamports": submission.solana_payment_lamports,
        "recorded_at": submission.solana_payment_at.isoformat(),
    }


@router.get("/filings/{submission_id}/progress")
async def filing_progress_endpoint(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Polling endpoint for robot progress.

    Returns the same shape as the check_filing_progress tool result
    so the frontend can mirror what the agent sees. Access is gated by
    the case the submission belongs to: only the owning user (or admins)
    can poll it.
    """
    from app.cases.models import Case
    from app.services.ukipo.models import UKIPOSubmission

    result = await db.execute(
        select(UKIPOSubmission).where(UKIPOSubmission.id == submission_id)
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    case_result = await db.execute(
        select(Case).where(Case.id == submission.case_id)
    )
    case = case_result.scalar_one_or_none()
    if case is None or (
        case.client_id != current_user.id
        and current_user.role.value != "admin"
    ):
        raise HTTPException(status_code=404, detail="Submission not found")

    try:
        nice_classes = json.loads(submission.nice_classes_json)
    except (TypeError, ValueError):
        nice_classes = []

    return {
        "submission_id": str(submission.id),
        "status": submission.status.value,
        "current_step": submission.current_step,
        "error_step": submission.error_step,
        "error_message": submission.error_message,
        "ipo_application_url": submission.ipo_application_url,
        "ipo_reference": submission.ipo_reference,
        "owner_company_name": submission.owner_company_name,
        "owner_country": submission.owner_country,
        "mark_text": submission.mark_text,
        "mark_type": submission.mark_type.value,
        "nice_classes": nice_classes,
        "started_at": submission.started_at.isoformat() if submission.started_at else None,
        "finished_at": submission.finished_at.isoformat() if submission.finished_at else None,
    }


@router.post(
    "/sessions/{session_id}/messages",
    response_model=TurnResponse,
)
async def send_message_endpoint(
    session_id: uuid.UUID,
    data: MessageSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TurnResponse:
    session = await service.get_session_for_user(
        db, session_id=session_id, user_id=current_user.id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    needs_title = session.title is None

    user_msg = await service.append_user_message(
        db, session=session, content=data.content
    )

    try:
        new_messages = await run_turn(db, session)
    except OrchestratorError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if needs_title:
        await service.generate_and_apply_session_title(
            db,
            session=session,
            first_user_message=data.content,
        )

    await db.flush()
    await db.refresh(session)

    return TurnResponse(
        session=SessionResponse.model_validate(session),
        messages=[user_msg, *new_messages],
    )

"""HTTP API for the agent orchestrator."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from solders.pubkey import Pubkey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import service, uploads as upload_service
from app.agent.download_token import verify_download_token
from app.agent.models import AgentUpload, AgentUploadStatus
from app.agent.orchestrator import OrchestratorError, run_turn
from app.agent.schemas import (
    AgentUploadListResponse,
    AgentUploadResponse,
    AttachUploadOwnershipRequest,
    FilingPaymentConfirmRequest,
    FilingPaymentConfirmResponse,
    MessageListResponse,
    MessageSendRequest,
    SessionCreateRequest,
    SessionListResponse,
    SessionRenameRequest,
    SessionResponse,
    TurnResponse,
)
from app.auth.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.security.virus_scan import scan_upload
from app.services.x402_core import (
    build_explorer_urls,
    compute_expected_memo,
    decode_compliance_proof,
    derive_filing_query_hash,
)
from app.solana.client import (
    SolanaClientError,
    derive_compliance_record_pda,
    fetch_file_ownership_record,
    submit_compliance_proof_tx,
    verify_payment_tx,
)
from app.users.models import User

router = APIRouter(prefix="/agent", tags=["agent"])

# Cap individual uploads to 25 MiB so a single multipart request cannot
# exhaust the worker memory budget. Matches the practical upper bound
# for image + PDF documents that vision validation can reason about.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


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
    """Return everything the wallet needs to build a real x402 + ZK-bound
    Solana payment tx for a UKIPO filing.

    The frontend reads this once when the robot reaches
    ``awaiting_payment`` and uses it to:

    1. Re-derive the canonical filing-context query hash locally
       (``sha256("etornie-filing-v1|<submission_id>|<mark_text>|<nice_classes_json>")``).
    2. Generate a Groth16 compliance proof for that query hash.
    3. Build the payment tx with memo
       ``base58(sha256(query_hash || commitment))``.
    4. POST the payment tx + proof to ``confirm-payment``.

    The backend re-derives the same query hash from this submission row
    on confirm, so the user cannot get away with paying for a different
    filing context than the one currently filed.
    """
    from app.cases.models import Case
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

    lamports = getattr(settings, "ukipo_payment_lamports", 0) or 0
    if lamports <= 0:
        raise HTTPException(
            status_code=500,
            detail="UKIPO_PAYMENT_LAMPORTS is not configured",
        )

    expected_query_hash = derive_filing_query_hash(
        submission_id=str(submission.id),
        mark_text=submission.mark_text,
        nice_classes_json=submission.nice_classes_json,
    )

    return {
        "submission_id": str(submission.id),
        "vault": vault,
        "lamports": lamports,
        "currency": "SOL",
        "network": (
            "solana-mainnet"
            if "mainnet" in settings.solana_cluster_url
            else "solana-devnet"
        ),
        "memo_scheme": "base58(sha256(query_hash || commitment))",
        "query_hash_hex": expected_query_hash.hex(),
        "query_hash_payload": (
            "etornie-filing-v1|<submission_id>|<mark_text>|<nice_classes_json>"
        ),
        "platform_fee_gbp": 265,
    }


@router.post(
    "/filings/{submission_id}/confirm-payment",
    response_model=FilingPaymentConfirmResponse,
)
async def filing_confirm_payment_endpoint(
    submission_id: uuid.UUID,
    data: FilingPaymentConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FilingPaymentConfirmResponse:
    """Confirm a UKIPO filing payment with a real x402 + Groth16 handshake.

    Mirrors the EtornieGPT chat flow:

    1. Decode the submitted Groth16 compliance proof and verify its
       structural consistency.
    2. Re-derive the canonical filing-context query hash from the
       submission row and assert it matches the proof's query hash and
       canonical halves.
    3. Compute the expected payment memo
       ``base58(sha256(query_hash || commitment))`` and verify the
       on-chain payment tx carries that memo, the configured vault as
       the recipient, and at least the configured lamports.
    4. Submit the verify_compliance_proof tx (operator signs alone)
       so the on-chain ComplianceRecord PDA gets initialised.
    5. Persist the full proof lineage on the submission row and flip
       its status to ``filed``.
    """
    from app.cases.models import Case
    from app.services.ukipo.models import UKIPOSubmission, UKIPOSubmissionStatus

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

    if submission.status not in (
        UKIPOSubmissionStatus.awaiting_payment,
        UKIPOSubmissionStatus.filed,
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Submission is in status '{submission.status.value}'; "
                "payment can only be confirmed once the robot reaches "
                "awaiting_payment."
            ),
        )

    vault_addr = (
        getattr(settings, "ukipo_payment_vault", "")
        or getattr(settings, "etorniegpt_payment_vault", "")
    )
    if not vault_addr:
        raise HTTPException(
            status_code=500,
            detail=(
                "Payment vault address is not configured "
                "(UKIPO_PAYMENT_VAULT or ETORNIEGPT_PAYMENT_VAULT)."
            ),
        )
    try:
        payer_pubkey = Pubkey.from_string(data.payer_wallet)
        vault_pubkey = Pubkey.from_string(vault_addr)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid pubkey: {exc}"
        ) from exc

    # Re-derive the canonical filing-context query hash from server-side
    # state. The proof must commit to this exact bytes, otherwise the
    # client signed a different payload than what we are about to file.
    expected_query_hash = derive_filing_query_hash(
        submission_id=str(submission.id),
        mark_text=submission.mark_text,
        nice_classes_json=submission.nice_classes_json,
    )

    decoded = decode_compliance_proof(
        proof_a_b64=data.compliance_proof.proof_a_b64,
        proof_b_b64=data.compliance_proof.proof_b_b64,
        proof_c_b64=data.compliance_proof.proof_c_b64,
        public_inputs_b64=data.compliance_proof.public_inputs_b64,
        query_hash_b64=data.compliance_proof.query_hash_b64,
        expected_query_hash=expected_query_hash,
    )

    expected_memo = compute_expected_memo(decoded.query_hash, decoded.commitment)
    min_lamports = getattr(settings, "ukipo_payment_lamports", 0) or 0
    if min_lamports <= 0:
        raise HTTPException(
            status_code=500,
            detail="UKIPO_PAYMENT_LAMPORTS is not configured",
        )

    try:
        await verify_payment_tx(
            signature=data.payment_tx,
            expected_recipient=vault_pubkey,
            min_lamports=min_lamports,
            expected_memo=expected_memo,
        )
    except SolanaClientError as exc:
        raise HTTPException(
            status_code=402, detail=f"payment verification failed: {exc}"
        ) from exc

    # Idempotency: if the same wallet already has a ComplianceRecord PDA
    # for this filing, the verifier program will reject the proof with
    # ReplayedProof. Reuse the existing on-chain record so a retry from
    # the user does not double-submit.
    existing_pda, _ = derive_compliance_record_pda(
        payer_pubkey, decoded.query_hash
    )
    if (
        submission.solana_compliance_pda
        and submission.solana_compliance_pda == str(existing_pda)
    ):
        compliance_tx = submission.solana_compliance_tx or ""
        compliance_pda_str = submission.solana_compliance_pda
    else:
        try:
            compliance_tx, compliance_pda = await submit_compliance_proof_tx(
                user=payer_pubkey,
                proof_a=decoded.proof_a,
                proof_b=decoded.proof_b,
                proof_c=decoded.proof_c,
                public_inputs=decoded.public_inputs,
                query_hash=decoded.query_hash,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SolanaClientError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"compliance proof submission failed: {exc}",
            ) from exc
        compliance_pda_str = str(compliance_pda)

    now = datetime.now(timezone.utc)
    submission.solana_payment_tx = data.payment_tx.strip()
    submission.solana_payer_wallet = data.payer_wallet.strip()
    submission.solana_payment_lamports = min_lamports
    submission.solana_payment_at = now
    submission.solana_query_hash_hex = decoded.query_hash.hex()
    submission.solana_commitment_hex = decoded.commitment.hex()
    submission.solana_compliance_tx = compliance_tx
    submission.solana_compliance_pda = compliance_pda_str
    submission.status = UKIPOSubmissionStatus.filed
    await db.commit()
    await db.refresh(submission)

    explorer = build_explorer_urls(
        payment_tx=submission.solana_payment_tx,
        compliance_tx=compliance_tx,
        compliance_pda=compliance_pda_str,
    )

    return FilingPaymentConfirmResponse(
        submission_id=submission.id,
        case_id=case.id,
        case_number=case.case_number,
        status=submission.status.value,
        payer_wallet=submission.solana_payer_wallet,
        payment_tx=submission.solana_payment_tx,
        payment_lamports=submission.solana_payment_lamports,
        payment_at=submission.solana_payment_at,
        query_hash_hex=submission.solana_query_hash_hex,
        commitment_hex=submission.solana_commitment_hex,
        compliance_tx=compliance_tx,
        compliance_pda=compliance_pda_str,
        payment_explorer_url=explorer["payment_explorer_url"],
        compliance_explorer_url=explorer["compliance_explorer_url"],
        compliance_record_explorer_url=explorer["compliance_record_explorer_url"],
    )


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
        "case_id": str(submission.case_id),
        "case_number": case.case_number,
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


# ---------------------------------------------------------------------------
# In-session file uploads
# ---------------------------------------------------------------------------


async def _load_owned_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
):
    session = await service.get_session_for_user(
        db, session_id=session_id, user_id=user_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _load_owned_upload(
    db: AsyncSession,
    *,
    upload_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AgentUpload:
    upload = await upload_service.get_upload(db, upload_id)
    if upload is None or upload.user_id != user_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload


@router.post(
    "/sessions/{session_id}/uploads",
    response_model=AgentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_to_session_endpoint(
    session_id: uuid.UUID,
    file: UploadFile,
    expected_document_type: str | None = Form(default=None),
    file_hash_hex: str | None = Form(default=None),
    ownership_commitment_hex: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentUploadResponse:
    """Attach a file to an agent session.

    The bytes are stored on disk; metadata + server-computed sha256 land
    in ``agent_upload``. Optional ``expected_document_type`` records what
    the agent has just asked the user for, so the vision tool can later
    compare the inferred content against the request.

    Optional ``file_hash_hex`` / ``ownership_commitment_hex`` carry a
    zero-knowledge ownership claim computed in the user's browser:
      * ``file_hash_hex`` MUST match the server-computed sha256;
      * the pair must be supplied together or not at all.

    Both fields are optional so a quick informational upload (e.g. a
    receipt the agent only needs to read) can skip the wallet popup.
    """
    await _load_owned_session(
        db, session_id=session_id, user_id=current_user.id
    )

    raw = await file.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit"
            ),
        )

    # Reject malware before the bytes are stored / vision-indexed (#55).
    await scan_upload(raw, filename=file.filename)

    try:
        upload = await upload_service.store_upload(
            db,
            session_id=session_id,
            user_id=current_user.id,
            original_filename=file.filename or "unnamed",
            file_bytes=raw,
            mime_type=file.content_type,
            expected_document_type=expected_document_type,
            file_hash_hex=file_hash_hex,
            ownership_commitment_hex=ownership_commitment_hex,
        )
    except upload_service.UploadStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return AgentUploadResponse.model_validate(upload)


@router.get(
    "/sessions/{session_id}/uploads",
    response_model=AgentUploadListResponse,
)
async def list_session_uploads_endpoint(
    session_id: uuid.UUID,
    include_cancelled: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentUploadListResponse:
    await _load_owned_session(
        db, session_id=session_id, user_id=current_user.id
    )
    rows = await upload_service.list_session_uploads(
        db, session_id=session_id, include_cancelled=include_cancelled
    )
    return AgentUploadListResponse(
        uploads=[AgentUploadResponse.model_validate(r) for r in rows]
    )


@router.get(
    "/uploads/{upload_id}",
    response_model=AgentUploadResponse,
)
async def get_upload_endpoint(
    upload_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentUploadResponse:
    upload = await _load_owned_upload(
        db, upload_id=upload_id, user_id=current_user.id
    )
    return AgentUploadResponse.model_validate(upload)


@router.get("/uploads/{upload_id}/download")
async def download_upload_endpoint(
    upload_id: uuid.UUID,
    request: Request,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download a file the agent or the user attached to a session.

    Accepted credentials (any one is enough):
      * ``Authorization: Bearer <jwt>`` — standard API auth.
      * ``?token=<signed>`` query param — short-lived HMAC token the
        agent attaches to download links so the user can click straight
        from a rendered chat message without a JWT bearer header.
    """
    upload = await upload_service.get_upload(db, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    auth_ok = False

    # 1. Signed token check.
    if token and verify_download_token(upload_id, token):
        auth_ok = True

    # 2. JWT bearer fallback. Inline (not via Depends) so missing/invalid
    #    headers do not short-circuit the signed-token path above.
    if not auth_ok:
        auth_header = request.headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            jwt_token = auth_header.split(" ", 1)[1].strip()
            try:
                from app.auth.utils import decode_token

                payload = decode_token(jwt_token)
                user_id_str = payload.get("sub")
                if user_id_str and uuid.UUID(user_id_str) == upload.user_id:
                    auth_ok = True
            except Exception:
                pass

    if not auth_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing or expired download token. Re-request the export "
                "from the agent to receive a fresh link, or call this "
                "endpoint with a valid JWT bearer."
            ),
        )

    if upload.status == AgentUploadStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Upload has been cancelled and the file is no longer available",
        )
    if not os.path.isfile(upload.stored_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
        )
    return FileResponse(
        path=upload.stored_path,
        filename=upload.original_filename,
        media_type=upload.mime_type or "application/octet-stream",
    )


@router.delete(
    "/uploads/{upload_id}",
    response_model=AgentUploadResponse,
)
async def cancel_upload_endpoint(
    upload_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentUploadResponse:
    upload = await _load_owned_upload(
        db, upload_id=upload_id, user_id=current_user.id
    )
    cancelled = await upload_service.cancel_upload(db, upload)
    return AgentUploadResponse.model_validate(cancelled)


@router.post(
    "/uploads/{upload_id}/attach-ownership-proof",
    response_model=AgentUploadResponse,
)
async def attach_upload_ownership_proof_endpoint(
    upload_id: uuid.UUID,
    req: AttachUploadOwnershipRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentUploadResponse:
    """Bind a confirmed on-chain FileOwnershipRecord PDA to an agent upload.

    Mirrors ``/documents/{document_id}/attach-ownership-proof`` so the
    same ZK pipeline serves both the cases-page upload UI and the
    in-session agent uploads. The server re-fetches the PDA from devnet
    and asserts the on-chain ``file_hash`` and ``commitment`` match the
    values recorded on this upload row.
    """
    upload = await _load_owned_upload(
        db, upload_id=upload_id, user_id=current_user.id
    )

    if upload.status == AgentUploadStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Upload has been cancelled",
        )

    if (
        upload.file_hash_hex is None
        or upload.ownership_commitment_hex is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Upload has no ownership commitment recorded at upload time; "
                "cannot attach a proof"
            ),
        )

    if upload.ownership_verified_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ownership proof already attached to this upload",
        )

    try:
        pda = Pubkey.from_string(req.proof_pda)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid proof_pda: {exc}",
        ) from exc

    try:
        record = await fetch_file_ownership_record(pda)
    except SolanaClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"On-chain verification failed: {exc}",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "FileOwnershipRecord not found at the given PDA, or PDA is "
                "not owned by the zk-verifier program"
            ),
        )

    if record.file_hash_hex != upload.file_hash_hex.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"On-chain file_hash {record.file_hash_hex} does not match "
                f"upload file_hash {upload.file_hash_hex}"
            ),
        )
    if record.commitment_hex != upload.ownership_commitment_hex.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"On-chain commitment {record.commitment_hex} does not match "
                f"upload commitment {upload.ownership_commitment_hex}"
            ),
        )

    upload.ownership_proof_pda = str(pda)
    upload.ownership_verified_at = datetime.fromtimestamp(
        record.verified_at, tz=timezone.utc
    )
    await db.flush()
    await db.refresh(upload)

    return AgentUploadResponse.model_validate(upload)

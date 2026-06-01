"""HTTP routes for UK IPO submissions.

POST /ukipo/submissions                       — create a pending row
POST /ukipo/submissions/{id}/run              — kick off the robot in
                                                the background; returns
                                                immediately with
                                                status=running
GET  /ukipo/submissions/{id}                  — fetch a single
                                                submission (frontend
                                                polls this for live
                                                progress)
GET  /ukipo/cases/{id}/submissions            — list submissions
GET  /ukipo/submissions/{id}/payment-requirements
                                              — Solana payment plan for
                                                the awaiting_payment
                                                state
POST /ukipo/submissions/{id}/payment          — verify + record the SOL
                                                payment

Run is fire-and-forget: the actual Playwright drive happens in an
``asyncio.create_task`` background coroutine, writing live ``current_step``
updates so the case detail page can poll and show progress.
"""

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.cases.service import get_case
from app.config import settings
from app.database import get_db
from app.security.virus_scan import scan_upload
from app.services.ukipo.schemas import (
    UKIPOPaymentRecordRequest,
    UKIPOPaymentRequirementsResponse,
    UKIPOSubmissionCreateRequest,
    UKIPOSubmissionListResponse,
    UKIPOSubmissionResponse,
)
from app.services.ukipo.service import (
    build_payment_requirements,
    create_submission,
    get_submission,
    list_submissions_for_case,
    record_solana_payment,
    start_submission_run,
)
from app.users.models import User, UserRole

router = APIRouter(prefix="/ukipo", tags=["ukipo"])

_ALLOWED_MARK_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg"}


class UKIPOMarkImageUploadResponse(BaseModel):
    path: str


def _can_access_case(user: User, case: object) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


@router.post(
    "/submissions",
    response_model=UKIPOSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission_endpoint(
    payload: UKIPOSubmissionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UKIPOSubmissionResponse:
    case = await get_case(db, payload.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")
    if current_user.role == UserRole.client:
        raise HTTPException(
            status_code=403,
            detail="Only admin or lawyer can create UK IPO submissions",
        )

    submission = await create_submission(
        db,
        case_id=payload.case_id,
        owner_company_name=payload.owner.company_name,
        owner_country=payload.owner.country,
        owner_address_line1=payload.owner.address_line1,
        owner_address_line2=payload.owner.address_line2,
        owner_city=payload.owner.city,
        owner_postcode=payload.owner.postcode,
        owner_email=payload.owner.email,
        owner_phone=payload.owner.phone,
        owner_entity_type=payload.owner.entity_type,
        owner_company_registration_number=payload.owner.company_registration_number,
        mark_type=payload.mark_type,
        mark_text=payload.mark_text,
        mark_image_path=payload.mark_image_path,
        nice_classes=[c.model_dump() for c in payload.nice_classes],
    )
    return UKIPOSubmissionResponse.model_validate(submission)


@router.post(
    "/submissions/{submission_id}/run",
    response_model=UKIPOSubmissionResponse,
)
async def run_submission_endpoint(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UKIPOSubmissionResponse:
    if current_user.role == UserRole.client:
        raise HTTPException(
            status_code=403,
            detail="Only admin or lawyer can run UK IPO submissions",
        )
    submission = await get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    case = await get_case(db, submission.case_id)
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        updated = await start_submission_run(db, submission)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return UKIPOSubmissionResponse.model_validate(updated)


@router.get(
    "/submissions/{submission_id}",
    response_model=UKIPOSubmissionResponse,
)
async def get_submission_endpoint(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UKIPOSubmissionResponse:
    submission = await get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    case = await get_case(db, submission.case_id)
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")
    return UKIPOSubmissionResponse.model_validate(submission)


@router.get(
    "/cases/{case_id}/submissions",
    response_model=UKIPOSubmissionListResponse,
)
async def list_submissions_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UKIPOSubmissionListResponse:
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")
    submissions = await list_submissions_for_case(db, case_id)
    return UKIPOSubmissionListResponse(
        submissions=[UKIPOSubmissionResponse.model_validate(s) for s in submissions],
        total=len(submissions),
    )


@router.get(
    "/submissions/{submission_id}/payment-requirements",
    response_model=UKIPOPaymentRequirementsResponse,
)
async def payment_requirements_endpoint(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UKIPOPaymentRequirementsResponse:
    submission = await get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    case = await get_case(db, submission.case_id)
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        plan = await build_payment_requirements(submission)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return UKIPOPaymentRequirementsResponse(**plan)


@router.post(
    "/cases/{case_id}/mark-image",
    response_model=UKIPOMarkImageUploadResponse,
)
async def upload_mark_image_endpoint(
    case_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UKIPOMarkImageUploadResponse:
    """Persist a trade-mark image so the robot can later set_input_files() it.

    Returns the absolute server path; the caller stores that path on
    the submission row and the robot reads it when filling the form.
    """
    if current_user.role == UserRole.client:
        raise HTTPException(
            status_code=403,
            detail="Only admin or lawyer can upload UK IPO mark images",
        )
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_MARK_IMAGE_EXT:
        raise HTTPException(
            status_code=400,
            detail=(
                "mark image must be one of: "
                + ", ".join(sorted(_ALLOWED_MARK_IMAGE_EXT))
            ),
        )

    case_dir = os.path.join(settings.upload_dir, "ukipo", str(case_id))
    os.makedirs(case_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4()}{ext}"
    abs_path = os.path.abspath(os.path.join(case_dir, safe_name))
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    # Reject malware before the mark image is persisted (#55).
    await scan_upload(content, filename=file.filename)
    with open(abs_path, "wb") as f:
        f.write(content)
    return UKIPOMarkImageUploadResponse(path=abs_path)


@router.post(
    "/submissions/{submission_id}/payment",
    response_model=UKIPOSubmissionResponse,
)
async def record_payment_endpoint(
    submission_id: uuid.UUID,
    payload: UKIPOPaymentRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UKIPOSubmissionResponse:
    submission = await get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    case = await get_case(db, submission.case_id)
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        updated = await record_solana_payment(
            db,
            submission,
            payment_tx=payload.payment_tx,
            payer_wallet=payload.payer_wallet,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return UKIPOSubmissionResponse.model_validate(updated)

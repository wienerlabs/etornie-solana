"""FastAPI endpoints for e-signature (issue #63).

- POST /esign/signature-requests        — send a case document to its
                                           client for e-signature (auth).
- GET  /esign/signature-requests        — list a case's requests (auth).
- GET  /esign/signature-requests/{id}   — read one request (auth).
- POST /esign/webhook                    — Yousign-signed event receiver.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.cases.models import Case
from app.database import get_db
from app.documents.models import Document
from app.esign import service as esign_service
from app.esign import yousign_client
from app.esign.models import SignatureRequest
from app.esign.schemas import (
    CreateSignatureRequestBody,
    SignatureRequestListResponse,
    SignatureRequestResponse,
)
from app.esign.yousign_client import EsignError
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/esign", tags=["esign"])


def _can_access_case(user: User, case: Case) -> bool:
    """Admins (operators) and the bound client may act on a case."""
    return user.role == UserRole.admin or user.id == case.client_id


def _to_response(row: SignatureRequest) -> SignatureRequestResponse:
    return SignatureRequestResponse(
        id=row.id,
        case_id=row.case_id,
        source_document_id=row.source_document_id,
        signed_document_id=row.signed_document_id,
        signer_email=row.signer_email,
        signer_name=row.signer_name,
        subject=row.subject,
        provider=row.provider.value,
        status=row.status.value,
        signing_url=row.signing_url,
        error=row.error,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post(
    "/signature-requests",
    response_model=SignatureRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_signature_request(
    body: CreateSignatureRequestBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SignatureRequestResponse:
    """Send a case document to the case client for e-signature."""
    case = (
        await db.execute(select(Case).where(Case.id == body.case_id))
    ).scalar_one_or_none()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have access to this case"
        )
    if case.client_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This case has no bound client to sign as.",
        )

    document = (
        await db.execute(
            select(Document).where(Document.id == body.document_id)
        )
    ).scalar_one_or_none()
    if document is None or document.case_id != case.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Document not found on this case"
        )

    signer = (
        await db.execute(select(User).where(User.id == case.client_id))
    ).scalar_one_or_none()
    if signer is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Case client account not found."
        )

    try:
        row = await esign_service.create_signature_request_for_document(
            db, case=case, document=document, signer=signer, subject=body.subject
        )
    except EsignError as exc:
        await db.commit()  # persist the error row before surfacing
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.get(
    "/signature-requests",
    response_model=SignatureRequestListResponse,
)
async def list_signature_requests(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SignatureRequestListResponse:
    """List signature requests for a case the caller can access."""
    case = (
        await db.execute(select(Case).where(Case.id == case_id))
    ).scalar_one_or_none()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have access to this case"
        )
    rows = await esign_service.list_for_case(db, case_id)
    return SignatureRequestListResponse(
        signature_requests=[_to_response(r) for r in rows]
    )


@router.get(
    "/signature-requests/{request_id}",
    response_model=SignatureRequestResponse,
)
async def get_signature_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SignatureRequestResponse:
    row = await esign_service.get_request(db, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    case = (
        await db.execute(select(Case).where(Case.id == row.case_id))
    ).scalar_one_or_none()
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return _to_response(row)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def yousign_webhook(
    request: Request,
    x_yousign_signature_256: str | None = Header(
        default=None, alias="X-Yousign-Signature-256"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a Yousign-signed webhook and reconcile the request row.

    The raw body is required for HMAC verification — do not parse JSON
    before verifying.
    """
    payload = await request.body()
    if not yousign_client.verify_webhook(payload, x_yousign_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Yousign webhook signature.",
        )
    import json

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body is not valid JSON.",
        )
    result = await esign_service.handle_webhook(db, event)
    return {"received": True, **result}

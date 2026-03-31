import os
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.cases.service import get_case
from app.config import settings
from app.database import get_db
from app.documents.schemas import (
    DocumentListResponse,
    DocumentResponse,
    ReviewRequest,
)
from app.documents.service import (
    cancel_document,
    create_document,
    get_document,
    list_documents,
    review_document,
)
from app.required_documents.service import link_document_to_requirement
from app.users.models import User, UserRole

router = APIRouter(tags=["documents"])


def _can_access_case(user: User, case: object) -> bool:
    """Check whether a user may view/interact with a case."""
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "assigned_lawyer_id", None):
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


@router.post(
    "/cases/{case_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_endpoint(
    case_id: uuid.UUID,
    file: UploadFile,
    document_type: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Upload a document to a case. Optionally specify document_type to link to a requirement."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    if not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this case",
        )

    # Build destination path
    case_dir = os.path.join(settings.upload_dir, str(case_id))
    os.makedirs(case_dir, exist_ok=True)

    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(case_dir, unique_filename)

    # Write file contents
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    document = await create_document(
        db,
        case_id=case_id,
        uploaded_by=current_user.id,
        filename=file.filename or "unnamed",
        file_path=file_path,
        file_type=file.content_type,
        file_size=len(content),
        document_type=document_type,
    )

    # Auto-link to case requirement if document_type matches
    if document_type:
        await link_document_to_requirement(
            db, case_id=case_id, document_type=document_type, document_id=document.id
        )

    # Send in-app notification to case participants (except uploader)
    from app.in_app_notifications.service import notify_document_uploaded

    recipients = set()
    if case.assigned_lawyer_id and case.assigned_lawyer_id != current_user.id:
        recipients.add(case.assigned_lawyer_id)
    if case.client_id and case.client_id != current_user.id:
        recipients.add(case.client_id)

    for rid in recipients:
        try:
            await notify_document_uploaded(
                db,
                case_id=case_id,
                case_title=case.title,
                uploader_name=current_user.full_name,
                uploader_id=current_user.id,
                recipient_id=rid,
                filename=file.filename or "unnamed",
            )
        except Exception:
            pass  # non-blocking

    return DocumentResponse.model_validate(document)


@router.get("/cases/{case_id}/documents", response_model=DocumentListResponse)
async def list_documents_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentListResponse:
    """List all documents for a case."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    if not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this case",
        )

    documents = await list_documents(db, case_id)
    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in documents],
        total=len(documents),
    )


@router.get("/documents/{document_id}/download")
async def download_document_endpoint(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Download a document file."""
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    from app.documents.models import DocumentStatus as DS

    if document.status == DS.cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This document has been cancelled and cannot be downloaded",
        )

    case = await get_case(db, document.case_id)
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this document",
        )

    if not os.path.isfile(document.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
        )

    return FileResponse(
        path=document.file_path,
        filename=document.filename,
        media_type=document.file_type or "application/octet-stream",
    )


@router.patch("/documents/{document_id}/cancel", response_model=DocumentResponse)
async def cancel_document_endpoint(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Cancel a document. Only admin or the original uploader. Irreversible."""
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    from app.documents.models import DocumentStatus as DS

    if document.status == DS.cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is already cancelled",
        )

    is_admin = current_user.role == UserRole.admin
    is_uploader = current_user.id == document.uploaded_by

    if not (is_admin or is_uploader):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or the uploader can cancel this document",
        )

    cancelled = await cancel_document(db, document, current_user.id)

    # If linked to a case requirement, reset requirement to pending
    from app.required_documents.models import CaseRequiredDocument
    from sqlalchemy import select, and_

    result = await db.execute(
        select(CaseRequiredDocument).where(
            and_(
                CaseRequiredDocument.document_id == document_id,
                CaseRequiredDocument.case_id == document.case_id,
            )
        )
    )
    case_req = result.scalar_one_or_none()
    if case_req is not None:
        from app.documents.models import DocumentStatus
        case_req.status = DocumentStatus.pending
        case_req.document_id = None
        await db.flush()

    return DocumentResponse.model_validate(cancelled)


@router.patch("/documents/{document_id}/review", response_model=DocumentResponse)
async def review_document_endpoint(
    document_id: uuid.UUID,
    data: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Approve or reject a document. Only admin or assigned lawyer may review."""
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    case = await get_case(db, document.case_id)
    is_admin = current_user.role == UserRole.admin
    is_assigned_lawyer = case is not None and current_user.id == case.assigned_lawyer_id

    if not (is_admin or is_assigned_lawyer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or assigned lawyer can review documents",
        )

    updated = await review_document(
        db,
        document=document,
        reviewer_id=current_user.id,
        action=data.action.value,
        rejection_reason=data.rejection_reason,
    )

    # Sync status to case_required_document if linked
    from app.required_documents.service import get_case_required_document
    from app.required_documents.models import CaseRequiredDocument
    from sqlalchemy import select, and_
    from app.documents.models import DocumentStatus

    result = await db.execute(
        select(CaseRequiredDocument).where(
            and_(
                CaseRequiredDocument.document_id == document_id,
                CaseRequiredDocument.case_id == document.case_id,
            )
        )
    )
    case_req = result.scalar_one_or_none()
    if case_req is not None:
        case_req.status = updated.status
        await db.flush()

    # Send in-app notification about the review result
    from app.in_app_notifications.service import notify_document_reviewed

    if case is not None:
        recipients = set()
        if case.client_id and case.client_id != current_user.id:
            recipients.add(case.client_id)
        if case.assigned_lawyer_id and case.assigned_lawyer_id != current_user.id:
            recipients.add(case.assigned_lawyer_id)

        for rid in recipients:
            try:
                await notify_document_reviewed(
                    db,
                    case_id=document.case_id,
                    case_title=case.title,
                    reviewer_name=current_user.full_name,
                    reviewer_id=current_user.id,
                    recipient_id=rid,
                    filename=document.filename,
                    approved=data.action.value == "approve",
                    rejection_reason=data.rejection_reason,
                )
            except Exception:
                pass

    return DocumentResponse.model_validate(updated)

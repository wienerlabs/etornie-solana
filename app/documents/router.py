import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.cases.service import get_case
from app.config import settings
from app.database import get_db
from app.documents.schemas import DocumentListResponse, DocumentResponse
from app.documents.service import (
    create_document,
    delete_document,
    get_document,
    list_documents,
)
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Upload a document to a case."""
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
    )
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


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_endpoint(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a document. Only admin or the original uploader may delete."""
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    is_admin = current_user.role == UserRole.admin
    is_uploader = current_user.id == document.uploaded_by

    if not (is_admin or is_uploader):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or the uploader can delete this document",
        )

    # Remove from filesystem if it exists
    if os.path.isfile(document.file_path):
        os.remove(document.file_path)

    await delete_document(db, document)

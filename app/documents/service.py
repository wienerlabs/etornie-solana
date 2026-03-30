import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentStatus


async def create_document(
    db: AsyncSession,
    case_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    filename: str,
    file_path: str,
    file_type: str | None,
    file_size: int | None,
    document_type: str | None = None,
) -> Document:
    """Persist a new document record."""
    document = Document(
        case_id=case_id,
        uploaded_by=uploaded_by,
        filename=filename,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        status=DocumentStatus.uploaded,
        document_type=document_type,
    )
    db.add(document)
    await db.flush()
    await db.refresh(document)
    return document


async def get_document(db: AsyncSession, document_id: uuid.UUID) -> Document | None:
    """Fetch a document by ID."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def list_documents(db: AsyncSession, case_id: uuid.UUID) -> list[Document]:
    """List all documents for a case, newest first."""
    result = await db.execute(
        select(Document)
        .where(Document.case_id == case_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_document(db: AsyncSession, document: Document) -> None:
    """Remove a document record from the database."""
    await db.delete(document)
    await db.flush()


async def review_document(
    db: AsyncSession,
    document: Document,
    reviewer_id: uuid.UUID,
    action: str,
    rejection_reason: str | None = None,
) -> Document:
    """Approve or reject a document."""
    document.reviewed_by = reviewer_id
    document.reviewed_at = datetime.now(timezone.utc)
    if action == "approve":
        document.status = DocumentStatus.approved
        document.rejection_reason = None
    else:
        document.status = DocumentStatus.rejected
        document.rejection_reason = rejection_reason
    await db.flush()
    await db.refresh(document)
    return document

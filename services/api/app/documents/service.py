import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction
from app.audit.service import log_cancellation
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
    file_hash_hex: str | None = None,
    ownership_commitment_hex: str | None = None,
) -> Document:
    """Persist a new document record.

    ``file_hash_hex`` and ``ownership_commitment_hex`` are optional
    zero-knowledge ownership fields computed in the user's browser at
    upload time. When supplied, they pin the document to an off-chain
    ownership commitment that can later be proved on-chain via
    ``/zk/file-ownership/submit``. See circuits/file_ownership/ for the
    circuit side.
    """
    document = Document(
        case_id=case_id,
        uploaded_by=uploaded_by,
        filename=filename,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        status=DocumentStatus.uploaded,
        document_type=document_type,
        file_hash_hex=file_hash_hex,
        ownership_commitment_hex=ownership_commitment_hex,
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


async def cancel_document(
    db: AsyncSession,
    document: Document,
    cancelled_by_id: uuid.UUID,
) -> Document:
    """Cancel a document (soft-delete). Irreversible."""
    document.status = DocumentStatus.cancelled
    document.cancelled_at = datetime.now(timezone.utc)
    document.cancelled_by = cancelled_by_id
    await db.flush()
    await db.refresh(document)

    await log_cancellation(
        db,
        actor_id=cancelled_by_id,
        action=AuditAction.document_cancelled,
        target_type="document",
        target_id=document.id,
        case_id=document.case_id,
        details=f"Document cancelled: {document.filename}",
    )

    return document


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

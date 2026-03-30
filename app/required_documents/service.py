import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentStatus
from app.required_documents.models import CaseRequiredDocument, RequiredDocumentTemplate


async def list_templates(
    db: AsyncSession,
    jurisdiction: str | None = None,
    case_type: str | None = None,
) -> list[RequiredDocumentTemplate]:
    """List active templates, optionally filtered by jurisdiction and case_type."""
    query = select(RequiredDocumentTemplate).where(
        RequiredDocumentTemplate.is_active.is_(True)
    )
    if jurisdiction is not None:
        query = query.where(RequiredDocumentTemplate.jurisdiction == jurisdiction)
    if case_type is not None:
        query = query.where(
            (RequiredDocumentTemplate.case_type == case_type)
            | (RequiredDocumentTemplate.case_type.is_(None))
        )
    result = await db.execute(query.order_by(RequiredDocumentTemplate.jurisdiction))
    return list(result.scalars().all())


async def create_template(
    db: AsyncSession,
    jurisdiction: str,
    document_name: str,
    case_type: str | None = None,
    description: str | None = None,
) -> RequiredDocumentTemplate:
    """Create a new required document template."""
    template = RequiredDocumentTemplate(
        jurisdiction=jurisdiction,
        case_type=case_type,
        document_name=document_name,
        description=description,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def generate_case_required_documents(
    db: AsyncSession,
    case_id: uuid.UUID,
    jurisdiction: str,
    case_type: str,
) -> list[CaseRequiredDocument]:
    """Generate required documents for a case based on templates.

    Matches templates where case_type matches or is null (applies to all types).
    """
    templates = await list_templates(db, jurisdiction=jurisdiction, case_type=case_type)
    created = []
    for tmpl in templates:
        # Check if this requirement already exists for the case
        existing = await db.execute(
            select(CaseRequiredDocument).where(
                and_(
                    CaseRequiredDocument.case_id == case_id,
                    CaseRequiredDocument.document_name == tmpl.document_name,
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        req = CaseRequiredDocument(
            case_id=case_id,
            document_name=tmpl.document_name,
            status=DocumentStatus.pending,
        )
        db.add(req)
        created.append(req)

    if created:
        await db.flush()
        for req in created:
            await db.refresh(req)

    return created


async def regenerate_on_jurisdiction_change(
    db: AsyncSession,
    case_id: uuid.UUID,
    new_jurisdiction: str,
    case_type: str,
) -> list[CaseRequiredDocument]:
    """Handle jurisdiction change: remove only pending requirements, then regenerate.

    uploaded/approved/rejected documents are preserved.
    """
    # Delete only pending requirements
    result = await db.execute(
        select(CaseRequiredDocument).where(
            and_(
                CaseRequiredDocument.case_id == case_id,
                CaseRequiredDocument.status == DocumentStatus.pending,
            )
        )
    )
    pending_reqs = list(result.scalars().all())
    for req in pending_reqs:
        await db.delete(req)
    await db.flush()

    return await generate_case_required_documents(
        db, case_id, new_jurisdiction, case_type
    )


async def list_case_required_documents(
    db: AsyncSession,
    case_id: uuid.UUID,
) -> list[CaseRequiredDocument]:
    """List all required documents for a case."""
    result = await db.execute(
        select(CaseRequiredDocument)
        .where(CaseRequiredDocument.case_id == case_id)
        .order_by(CaseRequiredDocument.created_at)
    )
    return list(result.scalars().all())


async def get_case_required_document(
    db: AsyncSession,
    req_id: uuid.UUID,
) -> CaseRequiredDocument | None:
    """Fetch a single case required document by ID."""
    result = await db.execute(
        select(CaseRequiredDocument).where(CaseRequiredDocument.id == req_id)
    )
    return result.scalar_one_or_none()


async def link_document_to_requirement(
    db: AsyncSession,
    case_id: uuid.UUID,
    document_type: str,
    document_id: uuid.UUID,
) -> CaseRequiredDocument | None:
    """Link an uploaded document to a matching case requirement.

    Matches pending or rejected requirements (rejected allows re-upload).
    Returns the updated requirement if found, None otherwise.
    """
    result = await db.execute(
        select(CaseRequiredDocument).where(
            and_(
                CaseRequiredDocument.case_id == case_id,
                CaseRequiredDocument.document_name == document_type,
                CaseRequiredDocument.status.in_(
                    [DocumentStatus.pending, DocumentStatus.rejected]
                ),
            )
        )
    )
    req = result.scalar_one_or_none()
    if req is None:
        return None

    req.document_id = document_id
    req.status = DocumentStatus.uploaded
    await db.flush()
    await db.refresh(req)
    return req

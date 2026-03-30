import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseNote, CaseStatus


async def _next_case_number(db: AsyncSession) -> str:
    """Generate the next case number in ETR-YYYY-NNNN format."""
    year = datetime.now(timezone.utc).year
    prefix = f"ETR-{year}-"

    result = await db.execute(
        select(func.count(Case.id)).where(Case.case_number.like(f"{prefix}%"))
    )
    count = result.scalar_one()
    sequence = count + 1
    return f"{prefix}{sequence:04d}"


async def create_case(db: AsyncSession, **kwargs: object) -> Case:
    """Create a new case with auto-generated case_number.

    Auto-generates required documents if jurisdiction and case_type are provided.
    """
    case_number = await _next_case_number(db)
    case = Case(case_number=case_number, **kwargs)
    db.add(case)
    await db.flush()
    await db.refresh(case)

    # Auto-generate required documents from templates
    if case.jurisdiction and case.case_type:
        from app.required_documents.service import generate_case_required_documents

        await generate_case_required_documents(
            db,
            case_id=case.id,
            jurisdiction=case.jurisdiction,
            case_type=case.case_type.value,
        )

    return case


async def get_case(db: AsyncSession, case_id: uuid.UUID) -> Case | None:
    """Fetch a single case by ID."""
    result = await db.execute(select(Case).where(Case.id == case_id))
    return result.scalar_one_or_none()


async def list_cases(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    client_id: uuid.UUID | None = None,
    lawyer_id: uuid.UUID | None = None,
    status: CaseStatus | None = None,
) -> tuple[list[Case], int]:
    """List cases with optional filters. Returns (cases, total_count)."""
    query = select(Case)
    count_query = select(func.count(Case.id))

    if client_id is not None:
        query = query.where(Case.client_id == client_id)
        count_query = count_query.where(Case.client_id == client_id)

    if lawyer_id is not None:
        query = query.where(Case.assigned_lawyer_id == lawyer_id)
        count_query = count_query.where(Case.assigned_lawyer_id == lawyer_id)

    if status is not None:
        query = query.where(Case.status == status)
        count_query = count_query.where(Case.status == status)

    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    result = await db.execute(
        query.offset(skip).limit(limit).order_by(Case.created_at.desc())
    )
    cases = list(result.scalars().all())
    return cases, total


async def update_case(db: AsyncSession, case: Case, **kwargs: object) -> Case:
    """Update case fields. Only non-None values are applied."""
    for key, value in kwargs.items():
        if value is not None:
            setattr(case, key, value)
    await db.flush()
    await db.refresh(case)
    return case


async def create_case_note(
    db: AsyncSession,
    case_id: uuid.UUID,
    author_id: uuid.UUID,
    content: str,
) -> CaseNote:
    """Create a note on a case."""
    note = CaseNote(case_id=case_id, author_id=author_id, content=content)
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return note


async def list_case_notes(db: AsyncSession, case_id: uuid.UUID) -> list[CaseNote]:
    """List all notes for a case, newest first."""
    result = await db.execute(
        select(CaseNote)
        .where(CaseNote.case_id == case_id)
        .order_by(CaseNote.created_at.desc())
    )
    return list(result.scalars().all())


async def get_case_note(db: AsyncSession, note_id: uuid.UUID) -> CaseNote | None:
    """Fetch a single case note by ID."""
    result = await db.execute(select(CaseNote).where(CaseNote.id == note_id))
    return result.scalar_one_or_none()


async def delete_case_note(db: AsyncSession, note: CaseNote) -> None:
    """Delete a case note."""
    await db.delete(note)
    await db.flush()

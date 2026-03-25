import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.cases.models import CaseStatus
from app.cases.schemas import (
    CaseCreate,
    CaseListResponse,
    CaseNoteCreate,
    CaseNoteResponse,
    CaseResponse,
    CaseUpdate,
)
from app.cases.service import (
    create_case,
    create_case_note,
    delete_case_note,
    get_case,
    get_case_note,
    list_case_notes,
    list_cases,
    update_case,
)
from app.database import get_db
from app.users.models import User, UserRole

router = APIRouter(prefix="/cases", tags=["cases"])


def _can_access_case(user: User, case: object) -> bool:
    """Check whether a user may view/interact with a case."""
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "assigned_lawyer_id", None):
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
async def create_case_endpoint(
    data: CaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> CaseResponse:
    """Create a new case (admin or lawyer only)."""
    case = await create_case(
        db,
        title=data.title,
        description=data.description,
        case_type=data.case_type,
        client_id=data.client_id,
        assigned_lawyer_id=data.assigned_lawyer_id,
        jurisdiction=data.jurisdiction,
        filing_date=data.filing_date,
        deadline=data.deadline,
    )
    return CaseResponse.model_validate(case)


@router.get("", response_model=CaseListResponse)
async def list_cases_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: CaseStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseListResponse:
    """List cases with role-based filtering.

    - Admin: all cases
    - Lawyer: only assigned cases
    - Client: only own cases
    """
    client_id: uuid.UUID | None = None
    lawyer_id: uuid.UUID | None = None

    if current_user.role == UserRole.client:
        client_id = current_user.id
    elif current_user.role == UserRole.lawyer:
        lawyer_id = current_user.id

    cases, total = await list_cases(
        db,
        skip=skip,
        limit=limit,
        client_id=client_id,
        lawyer_id=lawyer_id,
        status=status_filter,
    )
    return CaseListResponse(
        cases=[CaseResponse.model_validate(c) for c in cases],
        total=total,
    )


@router.get("/{case_id}", response_model=CaseResponse)
async def get_case_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    """Get case detail. Must be admin, assigned lawyer, or case client."""
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

    return CaseResponse.model_validate(case)


@router.patch("/{case_id}", response_model=CaseResponse)
async def update_case_endpoint(
    case_id: uuid.UUID,
    data: CaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    """Update a case. Admin can update any; assigned lawyer can update theirs."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    is_admin = current_user.role == UserRole.admin
    is_assigned_lawyer = current_user.id == case.assigned_lawyer_id

    if not (is_admin or is_assigned_lawyer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or assigned lawyer can update this case",
        )

    update_data = data.model_dump(exclude_unset=True)
    case = await update_case(db, case, **update_data)
    return CaseResponse.model_validate(case)


@router.post(
    "/{case_id}/notes",
    response_model=CaseNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_note_endpoint(
    case_id: uuid.UUID,
    data: CaseNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseNoteResponse:
    """Add a note to a case. Admin, assigned lawyer, or case client."""
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

    note = await create_case_note(
        db, case_id=case_id, author_id=current_user.id, content=data.content
    )
    return CaseNoteResponse.model_validate(note)


@router.get("/{case_id}/notes", response_model=list[CaseNoteResponse])
async def list_notes_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CaseNoteResponse]:
    """List notes for a case. Admin, assigned lawyer, or case client."""
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

    notes = await list_case_notes(db, case_id)
    return [CaseNoteResponse.model_validate(n) for n in notes]


@router.delete(
    "/{case_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_note_endpoint(
    case_id: uuid.UUID,
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a note. Admin, assigned lawyer, or note author may delete."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    note = await get_case_note(db, note_id)
    if note is None or note.case_id != case_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    is_admin = current_user.role == UserRole.admin
    is_assigned_lawyer = current_user.id == case.assigned_lawyer_id
    is_author = current_user.id == note.author_id

    if not (is_admin or is_assigned_lawyer or is_author):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin, assigned lawyer, or note author can delete this note",
        )

    await delete_case_note(db, note)

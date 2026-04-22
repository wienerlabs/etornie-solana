import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.auth.service import get_user_by_id
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
    cancel_case_note,
    create_case,
    create_case_note,
    get_case,
    get_case_note,
    list_case_notes,
    list_cases,
    update_case,
)
from app.database import get_db
from app.notifications.case_notifications import (
    notify_case_created,
    send_case_created_email_to_guest,
    send_case_created_whatsapp_to_guest,
)
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

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
    # Auto-assign lawyer if current user is a lawyer and no lawyer specified
    assigned_lawyer_id = data.assigned_lawyer_id
    if assigned_lawyer_id is None and current_user.role == UserRole.lawyer:
        assigned_lawyer_id = current_user.id

    create_kwargs: dict[str, object] = {
        "title": data.title,
        "description": data.description,
        "case_type": data.case_type,
        "client_id": data.client_id,
        "assigned_lawyer_id": assigned_lawyer_id,
        "jurisdiction": data.jurisdiction,
        "nice_classes": data.nice_classes,
        "filing_date": data.filing_date,
        "deadline": data.deadline,
    }

    if data.client_id is None:
        create_kwargs["guest_client_name"] = data.guest_client_name
        create_kwargs["guest_client_email"] = data.guest_client_email
        create_kwargs["guest_client_phone"] = data.guest_client_phone

    case = await create_case(db, **create_kwargs)

    # Auto-generate proposal if nice_classes and jurisdiction are set
    if case.nice_classes and case.jurisdiction:
        try:
            from app.proposals.service import generate_proposal

            await generate_proposal(
                db,
                case_id=case.id,
                jurisdiction=case.jurisdiction,
                nice_classes=case.nice_classes,
                created_by=current_user.id,
            )
            logger.info(
                "Auto-generated proposal for case %s (jurisdiction=%s, nice_classes=%s)",
                case.case_number,
                case.jurisdiction,
                case.nice_classes,
            )
        except Exception as exc:
            logger.warning("Failed to auto-generate proposal for case %s: %s", case.case_number, exc)
            await db.rollback()
            await db.refresh(case)

    # Send notifications to the client (non-blocking)
    if data.client_id:
        client_user = await get_user_by_id(db, case.client_id)
        if client_user:
            try:
                await notify_case_created(db, case, client_user, current_user.id)
            except Exception as exc:
                logger.warning("Failed to send case notifications: %s", exc)
    else:
        # Guest client notifications
        try:
            if data.guest_client_email:
                await send_case_created_email_to_guest(
                    email=data.guest_client_email,
                    name=data.guest_client_name or "Client",
                    case=case,
                )
        except Exception as exc:
            logger.warning("Failed to send guest email notification: %s", exc)

        try:
            if data.guest_client_phone:
                await send_case_created_whatsapp_to_guest(
                    db=db,
                    phone=data.guest_client_phone,
                    name=data.guest_client_name or "Client",
                    case=case,
                    created_by_id=current_user.id,
                )
        except Exception as exc:
            logger.warning("Failed to send guest WhatsApp notification: %s", exc)

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

    old_jurisdiction = case.jurisdiction
    update_data = data.model_dump(exclude_unset=True)
    case = await update_case(db, case, **update_data)

    # Regenerate required documents if jurisdiction changed
    new_jurisdiction = case.jurisdiction
    if (
        new_jurisdiction
        and old_jurisdiction != new_jurisdiction
        and case.case_type
    ):
        from app.required_documents.service import regenerate_on_jurisdiction_change

        await regenerate_on_jurisdiction_change(
            db,
            case_id=case.id,
            new_jurisdiction=new_jurisdiction,
            case_type=case.case_type.value,
        )

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

    # Send in-app notification to case participants (except author)
    from app.in_app_notifications.service import notify_note_added

    recipients = set()
    if case.assigned_lawyer_id and case.assigned_lawyer_id != current_user.id:
        recipients.add(case.assigned_lawyer_id)
    if case.client_id and case.client_id != current_user.id:
        recipients.add(case.client_id)

    for rid in recipients:
        try:
            await notify_note_added(
                db,
                case_id=case_id,
                case_title=case.title,
                author_name=current_user.full_name,
                author_id=current_user.id,
                recipient_id=rid,
            )
        except Exception:
            pass

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


@router.patch(
    "/{case_id}/notes/{note_id}/cancel",
    response_model=CaseNoteResponse,
)
async def cancel_note_endpoint(
    case_id: uuid.UUID,
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseNoteResponse:
    """Cancel a note. Only the author or admin can cancel. Irreversible."""
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

    if note.is_cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Note is already cancelled",
        )

    is_admin = current_user.role == UserRole.admin
    is_author = current_user.id == note.author_id

    if not (is_admin or is_author):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or the note author can cancel this note",
        )

    cancelled = await cancel_case_note(db, note, current_user.id)
    return CaseNoteResponse.model_validate(cancelled)

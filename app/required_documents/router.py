import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.cases.service import get_case
from app.database import get_db
from app.required_documents.schemas import (
    CaseRequiredDocumentListResponse,
    CaseRequiredDocumentResponse,
    RequiredDocumentTemplateCreate,
    RequiredDocumentTemplateResponse,
    TemplateListResponse,
)
from app.required_documents.service import (
    create_template,
    generate_case_required_documents,
    list_case_required_documents,
    list_templates,
)
from app.users.models import User, UserRole

router = APIRouter(tags=["required-documents"])


def _can_access_case(user: User, case: object) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "assigned_lawyer_id", None):
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


# --- Template endpoints (admin) ---


@router.get(
    "/required-documents/templates",
    response_model=TemplateListResponse,
)
async def list_templates_endpoint(
    jurisdiction: str | None = Query(default=None),
    case_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> TemplateListResponse:
    """List required document templates, optionally filtered."""
    templates = await list_templates(db, jurisdiction=jurisdiction, case_type=case_type)
    return TemplateListResponse(
        templates=[
            RequiredDocumentTemplateResponse.model_validate(t) for t in templates
        ],
        total=len(templates),
    )


@router.post(
    "/required-documents/templates",
    response_model=RequiredDocumentTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template_endpoint(
    data: RequiredDocumentTemplateCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.admin)),
) -> RequiredDocumentTemplateResponse:
    """Create a new required document template (admin only)."""
    template = await create_template(
        db,
        jurisdiction=data.jurisdiction,
        document_name=data.document_name,
        case_type=data.case_type,
        description=data.description,
    )
    return RequiredDocumentTemplateResponse.model_validate(template)


# --- Case required documents endpoints ---


@router.get(
    "/cases/{case_id}/required-documents",
    response_model=CaseRequiredDocumentListResponse,
)
async def list_case_required_documents_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseRequiredDocumentListResponse:
    """List required documents for a case. Accessible by case participants."""
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

    reqs = await list_case_required_documents(db, case_id)
    return CaseRequiredDocumentListResponse(
        required_documents=[
            CaseRequiredDocumentResponse.model_validate(r) for r in reqs
        ],
        total=len(reqs),
    )


@router.post(
    "/cases/{case_id}/required-documents/generate",
    response_model=CaseRequiredDocumentListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_case_required_documents_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> CaseRequiredDocumentListResponse:
    """Generate required documents for a case based on its jurisdiction and case_type."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    if not case.jurisdiction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Case jurisdiction is not set",
        )

    existing = await list_case_required_documents(db, case_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Zorunlu evraklar zaten oluşturulmuş",
        )

    created = await generate_case_required_documents(
        db,
        case_id=case_id,
        jurisdiction=case.jurisdiction,
        case_type=case.case_type.value,
    )
    return CaseRequiredDocumentListResponse(
        required_documents=[
            CaseRequiredDocumentResponse.model_validate(r) for r in created
        ],
        total=len(created),
    )

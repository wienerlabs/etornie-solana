"""GET /case-templates — list the one-click case templates (issue #65)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.cases.templates import CASE_TEMPLATES
from app.users.models import User

router = APIRouter(prefix="/case-templates", tags=["case-templates"])


class CaseTemplateOption(BaseModel):
    key: str
    name: str
    description: str
    case_type: str
    default_title: str
    default_description: str
    default_jurisdiction: str | None
    default_nice_classes: str | None


class CaseTemplateListResponse(BaseModel):
    templates: list[CaseTemplateOption]


@router.get("", response_model=CaseTemplateListResponse)
async def list_case_templates(
    _: User = Depends(get_current_user),
) -> CaseTemplateListResponse:
    """List the available case templates for the create-case picker."""
    return CaseTemplateListResponse(
        templates=[
            CaseTemplateOption(
                key=t.key,
                name=t.name,
                description=t.description,
                case_type=t.case_type.value,
                default_title=t.default_title,
                default_description=t.default_description,
                default_jurisdiction=t.default_jurisdiction,
                default_nice_classes=t.default_nice_classes,
            )
            for t in CASE_TEMPLATES
        ]
    )

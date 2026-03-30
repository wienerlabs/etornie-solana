import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.documents.models import DocumentStatus


class RequiredDocumentTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    jurisdiction: str
    case_type: str | None
    document_name: str
    description: str | None
    is_active: bool
    created_at: datetime


class RequiredDocumentTemplateCreate(BaseModel):
    jurisdiction: str = Field(max_length=10)
    case_type: str | None = Field(default=None, max_length=50)
    document_name: str = Field(max_length=500)
    description: str | None = None


class CaseRequiredDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    document_name: str
    status: DocumentStatus
    document_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class CaseRequiredDocumentListResponse(BaseModel):
    required_documents: list[CaseRequiredDocumentResponse]
    total: int


class TemplateListResponse(BaseModel):
    templates: list[RequiredDocumentTemplateResponse]
    total: int

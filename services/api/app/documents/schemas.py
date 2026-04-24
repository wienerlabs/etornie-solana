import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.documents.models import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    uploaded_by: uuid.UUID
    filename: str
    file_type: str | None
    file_size: int | None
    status: DocumentStatus
    document_type: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    cancelled_at: datetime | None = None
    cancelled_by: uuid.UUID | None = None
    file_hash_hex: str | None = None
    ownership_commitment_hex: str | None = None
    ownership_proof_pda: str | None = None
    ownership_verified_at: datetime | None = None
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class ReviewAction(str, Enum):
    approve = "approve"
    reject = "reject"


class ReviewRequest(BaseModel):
    action: ReviewAction
    rejection_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_rejection_reason(self) -> "ReviewRequest":
        if self.action == ReviewAction.reject and not self.rejection_reason:
            msg = "rejection_reason is required when rejecting a document"
            raise ValueError(msg)
        return self

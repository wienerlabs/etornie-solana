"""Request / response schemas for the /esign router (issue #63)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class CreateSignatureRequestBody(BaseModel):
    """Send a case document to the case client for e-signature."""

    case_id: uuid.UUID
    document_id: uuid.UUID = Field(
        ..., description="The case document (PDF) to be signed."
    )
    subject: str | None = Field(
        default=None,
        max_length=255,
        description="Optional title shown in the signer email + dashboard.",
    )


class SignatureRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    source_document_id: uuid.UUID | None
    signed_document_id: uuid.UUID | None
    signer_email: str
    signer_name: str
    subject: str
    provider: str
    status: str
    signing_url: str | None
    error: str | None
    created_at: str
    updated_at: str


class SignatureRequestListResponse(BaseModel):
    signature_requests: list[SignatureRequestResponse]

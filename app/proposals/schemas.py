import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.proposals.models import ProposalStatus


class ProposalRespondRequest(BaseModel):
    accepted: bool
    rejection_reason: str | None = Field(default=None, max_length=2000)


class ProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    country_name: str
    country_code: str | None
    nice_classes: str
    required_documents: str | None
    registration_period: str | None
    protection_period: str | None
    madrid_system: str | None
    national_application: str | None
    opposition_period: str | None
    special_notes: str | None
    price: Decimal | None
    currency: str | None
    status: ProposalStatus
    created_by: uuid.UUID
    rejection_reason: str | None = None
    sent_at: datetime | None
    responded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProposalListResponse(BaseModel):
    proposals: list[ProposalResponse]
    total: int

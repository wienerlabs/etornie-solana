import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.cases.models import CaseStatus, CaseType


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    case_type: CaseType
    client_id: uuid.UUID | None = None
    assigned_lawyer_id: uuid.UUID | None = None
    jurisdiction: str | None = Field(default=None, max_length=255)
    nice_classes: str | None = Field(default=None, max_length=500)
    filing_date: date | None = None
    deadline: date | None = None
    deadline_time: time | None = None
    # Guest client fields (used when client is not registered)
    guest_client_name: str | None = Field(default=None, max_length=255)
    guest_client_email: str | None = None
    guest_client_phone: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_client_info(self) -> "CaseCreate":
        """Either client_id or guest client info must be provided."""
        if self.client_id is not None:
            return self
        if self.guest_client_name and (
            self.guest_client_email or self.guest_client_phone
        ):
            return self
        msg = (
            "Either client_id or guest_client_name with at least one of "
            "guest_client_email/guest_client_phone must be provided."
        )
        raise ValueError(msg)


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    case_type: CaseType | None = None
    status: CaseStatus | None = None
    assigned_lawyer_id: uuid.UUID | None = None
    jurisdiction: str | None = Field(default=None, max_length=255)
    nice_classes: str | None = Field(default=None, max_length=500)
    filing_date: date | None = None
    deadline: date | None = None
    deadline_time: time | None = None


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    case_number: str
    case_type: CaseType
    status: CaseStatus
    client_id: uuid.UUID | None
    assigned_lawyer_id: uuid.UUID | None
    jurisdiction: str | None
    nice_classes: str | None = None
    filing_date: date | None
    deadline: date | None
    deadline_time: time | None
    guest_client_name: str | None = None
    guest_client_email: str | None = None
    guest_client_phone: str | None = None
    created_at: datetime
    updated_at: datetime


class CaseListResponse(BaseModel):
    cases: list[CaseResponse]
    total: int


class CaseNoteCreate(BaseModel):
    content: str = Field(min_length=1)


class CaseNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    author_id: uuid.UUID
    content: str
    is_cancelled: bool
    cancelled_at: datetime | None = None
    cancelled_by: uuid.UUID | None = None
    created_at: datetime

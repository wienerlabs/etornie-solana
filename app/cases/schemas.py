import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.cases.models import CaseStatus, CaseType


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    case_type: CaseType
    client_id: uuid.UUID
    assigned_lawyer_id: uuid.UUID | None = None
    jurisdiction: str | None = Field(default=None, max_length=255)
    filing_date: date | None = None
    deadline: date | None = None
    deadline_time: time | None = None


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    case_type: CaseType | None = None
    status: CaseStatus | None = None
    assigned_lawyer_id: uuid.UUID | None = None
    jurisdiction: str | None = Field(default=None, max_length=255)
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
    client_id: uuid.UUID
    assigned_lawyer_id: uuid.UUID | None
    jurisdiction: str | None
    filing_date: date | None
    deadline: date | None
    deadline_time: time | None
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
    created_at: datetime

import uuid
from datetime import date

from pydantic import BaseModel, Field


class DeadlineAlert(BaseModel):
    case_id: uuid.UUID
    case_number: str
    case_title: str
    deadline: date
    days_remaining: int
    interval_type: str = "days"
    interval_value: int = 0
    lawyer_name: str | None = None
    client_name: str | None = None
    notifications_created: int


class IPAgentRunResponse(BaseModel):
    scanned_cases: int
    deadlines_found: int
    notifications_created: int
    alerts: list[DeadlineAlert]


class UpcomingDeadlineItem(BaseModel):
    case_id: uuid.UUID
    case_number: str
    case_title: str
    deadline: date
    days_remaining: int
    status: str
    lawyer_name: str | None = None
    client_name: str | None = None

    model_config = {"from_attributes": True}


class UpcomingDeadlinesResponse(BaseModel):
    deadlines: list[UpcomingDeadlineItem]
    total: int


class AgentConfigureRequest(BaseModel):
    reminder_days: list[int] = Field(default=[30, 7, 1])
    reminder_minutes: list[int] = Field(default=[30, 10, 5, 1])
    enabled: bool = True


class AgentConfigResponse(BaseModel):
    agent_name: str
    is_enabled: bool
    reminder_days: list[int]
    reminder_minutes: list[int]

    model_config = {"from_attributes": True}

"""Pydantic schemas for the agent orchestrator API."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.agent.models import (
    AgentMessageRole,
    AgentSessionStatus,
)


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    status: AgentSessionStatus
    model: str
    total_input_tokens: int
    total_output_tokens: int
    started_at: datetime
    last_activity_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class MessageSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: AgentMessageRole
    content: str | None
    tool_call_id: str | None
    tool_name: str | None
    tool_arguments: dict | None
    tool_result: dict | None
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]


class TurnResponse(BaseModel):
    """Result of a single user-message → agent-reply round trip.

    `messages` includes the user message, any intermediate tool calls/
    results, and the final assistant message — in chronological order.
    """

    session: SessionResponse
    messages: list[MessageResponse]

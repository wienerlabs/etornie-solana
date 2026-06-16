import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PublicChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="tr", max_length=8)


class PublicChatResponse(BaseModel):
    answer: str
    country_detected: str | None = None
    model: str


class CreateApiKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)


class ApiKeyCreatedResponse(BaseModel):
    """Returned once at creation — ``api_key`` is the only time the plaintext
    is exposed."""

    id: uuid.UUID
    label: str
    api_key: str
    rate_limit_per_minute: int


class ApiKeyInfo(BaseModel):
    id: uuid.UUID
    label: str
    is_active: bool
    rate_limit_per_minute: int
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}

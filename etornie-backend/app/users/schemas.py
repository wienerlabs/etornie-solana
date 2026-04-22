import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.users.models import UserRole


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
    full_name: str
    phone: str | None = None
    role: UserRole
    is_active: bool
    is_verified: bool = False
    bar_association: str | None = None
    bar_number: str | None = None
    wallet_address: str | None = None
    public_handle: str | None = None
    auth_method: str = "email"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    role: UserRole | None = None
    is_active: bool | None = None
    bar_association: str | None = Field(default=None, max_length=255)
    bar_number: str | None = Field(default=None, max_length=64)


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int

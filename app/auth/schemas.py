import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.users.models import UserRole


WalletRegisterRole = Literal["client", "lawyer"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    role: UserRole = UserRole.client
    bar_association: str | None = Field(default=None, max_length=255)
    bar_number: str | None = Field(default=None, max_length=64)


class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str


class TokenPayload(BaseModel):
    sub: str
    role: str | None = None
    type: str
    exp: int


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


class WalletNonceRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=44)


class WalletNonceResponse(BaseModel):
    wallet_address: str
    nonce: str
    message: str
    expires_at: datetime


class WalletVerifyRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=44)
    message: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    full_name: str | None = Field(default=None, max_length=255)
    role: WalletRegisterRole | None = None
    bar_association: str | None = Field(default=None, max_length=255)
    bar_number: str | None = Field(default=None, max_length=64)


class WalletVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse

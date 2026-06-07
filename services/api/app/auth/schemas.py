import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.users.models import UserRole


WalletRegisterRole = Literal["client"]


_PUBLIC_REGISTER_ROLES = {UserRole.client}


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
    """Admin-only register payload — admin role permitted."""

    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    role: UserRole = UserRole.client


class PublicRegisterRequest(BaseModel):
    """Public register payload — admin role rejected."""

    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    role: UserRole = UserRole.client

    @field_validator("role")
    @classmethod
    def _no_admin_self_signup(cls, value: UserRole) -> UserRole:
        if value not in _PUBLIC_REGISTER_ROLES:
            raise ValueError(
                "admin role cannot be self-assigned via public registration"
            )
        return value


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
    wallet_address: str | None = None
    evm_address: str | None = None
    public_handle: str | None = None
    auth_method: str = "email"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EvmNonceRequest(BaseModel):
    address: str = Field(min_length=42, max_length=42)


class EvmNonceResponse(BaseModel):
    address: str
    nonce: str
    message: str
    expires_at: datetime


class EvmLinkRequest(BaseModel):
    address: str = Field(min_length=42, max_length=42)
    message: str = Field(min_length=1)
    signature: str = Field(min_length=1)


class EvmLinkStatus(BaseModel):
    linked: bool
    evm_address: str | None = None


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


class WalletVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse

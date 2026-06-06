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


class LoginResponse(BaseModel):
    """Login result.

    When the account has 2FA disabled this carries the token pair
    directly. When 2FA is enabled, ``access_token``/``refresh_token``
    stay null and ``mfa_required`` is true with a short-lived
    ``mfa_token`` the client exchanges at /auth/login/mfa.
    """

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None


class MfaLoginRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=4, max_length=32)


class TwoFactorStatusResponse(BaseModel):
    enabled: bool
    required: bool
    recovery_codes_remaining: int


class TwoFactorEnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_data_url: str


class TwoFactorEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class TwoFactorEnableResponse(BaseModel):
    enabled: bool = True
    recovery_codes: list[str]


class TwoFactorDisableRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)


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
    public_handle: str | None = None
    auth_method: str = "email"
    totp_enabled: bool = False
    mfa_setup_required: bool = False
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


class WalletVerifyResponse(BaseModel):
    """Wallet sign-in result.

    Mirrors :class:`LoginResponse`: when the resolved account has 2FA
    enabled, the token pair stays null and ``mfa_required`` is true with
    a short-lived ``mfa_token`` exchanged at /auth/login/mfa. ``user`` is
    always present so the client can run its role check either way.
    """

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None
    user: UserResponse

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, computed_field

from app.users.models import UserRole


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
    avatar_mime: str | None = None
    avatar_path: str | None = Field(default=None, exclude=True)
    # Opt-in notification settings — wallet users can fill these in
    # from the settings page to start receiving Stripe receipts,
    # EUIPO updates, refund confirmations, etc.
    notification_email: EmailStr | None = None
    email_notifications_enabled: bool = False
    # Multi-tenancy: the org the next /auth/me-driven UI defaults
    # to. Nullable for users with no membership (should be rare
    # post-backfill).
    default_organization_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[misc]
    @property
    def has_avatar(self) -> bool:
        # avatar_mime is set whenever an avatar exists (DB bytes or a legacy
        # disk file), so presence is reported without loading the bytes.
        return bool(self.avatar_mime)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    role: UserRole | None = None
    is_active: bool | None = None
    notification_email: EmailStr | None = None
    email_notifications_enabled: bool | None = None


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


class ErasureRequest(BaseModel):
    """Self-service GDPR erasure confirmation.

    The frontend gates this behind a typed confirmation; ``password`` is
    required for accounts that have one (re-authentication for an
    irreversible action) and ignored for wallet-only accounts.
    """

    password: str | None = None


class AdminErasureRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class ErasureBlockingCase(BaseModel):
    id: uuid.UUID
    case_number: str | None = None
    title: str | None = None
    status: str

    model_config = {"from_attributes": True}


class ErasureSummaryResponse(BaseModel):
    user_id: uuid.UUID
    erased_at: datetime
    anonymised: bool
    deleted_rows: dict[str, int]
    deleted_files: int
    retained_tables: list[str]

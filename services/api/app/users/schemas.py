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
        return bool(self.avatar_path)


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

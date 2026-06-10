from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiKey(Base):
    """A partner API key for the answer-only public Q&A endpoint.

    Only the SHA-256 hash of the key is stored; the plaintext is shown once
    at creation and never persisted. ``rate_limit_per_minute`` is enforced
    per key (see app/public_api/security.py).
    """

    __tablename__ = "api_keys"

    # ``id`` (uuid PK) comes from Base.

    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

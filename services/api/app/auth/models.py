"""Persisted refresh tokens — rotation + reuse detection (issue #35).

Refresh tokens are no longer stateless JWTs: each redemption is
recorded here so a token can be used exactly once, and a second
redemption of an already-used token (theft signal) revokes every
other token in the same family.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # All tokens issued across one login session share a family_id.
    # Rotating advances the family's current token; a reuse of any
    # redeemed token in the family revokes the whole family.
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    # sha256 hex digest of the raw opaque token. The raw token is
    # never stored — only ever returned once to the client at issuance
    # or rotation time.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

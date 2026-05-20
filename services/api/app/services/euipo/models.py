"""SQLAlchemy model for the persisted EUIPO OAuth session.

Singleton row (id=1) holding the operator-wide refresh_token. Lives in
``app/services/euipo/`` rather than a generic auth module because EUIPO
is the only provider that ships with this kind of long-lived
authorization_code session — other OAuth integrations either use
client_credentials (no refresh) or per-user tokens stored elsewhere.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EuipoOAuthToken(Base):
    __tablename__ = "euipo_oauth_token"

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_euipo_oauth_token_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

"""SQLAlchemy model for BRAID agent audit decisions.

One row per capability invocation made by the OpenServ BRAID agent in
``services/braid``. The agent posts to ``POST /braid/decisions`` after
each capability runs (fire-and-forget); the result is queryable via
``GET /braid/decisions[/...]`` for auditors / regulators / lawyers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BraidDecision(Base):
    __tablename__ = "braid_decisions"

    workspace_id: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    thread_id: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    capability_name: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

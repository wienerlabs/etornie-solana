"""Renewal reminder audit table.

Every email + in-app reminder the dispatcher sends gets one row here so
a re-run of the nightly job cannot double-fire on the same window.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


_JSONType: Any = JSON().with_variant(JSONB, "postgresql")


class RenewalReminder(Base):
    __tablename__ = "renewal_reminder"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    target_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    channels: Mapped[list[str]] = mapped_column(
        _JSONType,
        nullable=False,
        default=list,
    )

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "window_days",
            "target_due_at",
            name="uq_renewal_reminder_case_window_target",
        ),
    )

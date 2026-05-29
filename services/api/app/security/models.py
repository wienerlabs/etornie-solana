"""OperatorKeyAccessLog — append-only audit trail for operator key reads.

Every call to ``_load_operator()`` writes one row. The table is
intentionally narrow: timestamp, calling-code context, kind of
operation (sign / verify / inspect), success boolean. The actual key
material never lands here; the row only proves that a read happened.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OperatorKeyAccessLog(Base):
    __tablename__ = "operator_key_access_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    # Calling-code context — "compliance.submit_onchain_attestation",
    # "agent.tool.submit_filing", etc. Free-form so a future caller
    # does not need a migration to log a new operation kind.
    caller_context: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    # ``op_kind`` is normalised to a small enum-ish set:
    # ``sign``, ``verify``, ``inspect`` — keeps the admin filter
    # cardinality bounded.
    op_kind: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Free-form note carrying e.g. the failure reason. Capped at 500
    # chars in code so the table cannot bloat from a runaway stack
    # trace.
    note: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

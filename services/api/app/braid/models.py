"""SQLAlchemy model for BRAID agent audit decisions.

One row per capability invocation made by the OpenServ BRAID agent in
``services/braid``. The agent posts to ``POST /braid/decisions`` after
each capability runs (fire-and-forget); the result is queryable via
``GET /braid/decisions[/...]`` for auditors / regulators / lawyers.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# JSONB on PostgreSQL, plain JSON elsewhere (e.g. SQLite for tests).
_JSONType = JSON().with_variant(JSONB, "postgresql")


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
    args: Mapped[dict[str, Any]] = mapped_column(_JSONType, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONType, nullable=True
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


class BraidCalibrationEvent(Base):
    """One row per resolved feedback event linking a decision to its
    actual ground-truth outcome.

    A capability surfaces a stated confidence in its result (most of
    our capabilities populate ``result.confidence`` or
    ``result.risk_level``); after the lawyer/admin acts on the
    decision, they emit a feedback signal (correct / incorrect /
    inconclusive) and we record the pair so we can compute calibration
    error per capability over time. ``log_update`` and ``reward`` are
    the bounded values we actually applied to the weights table; we
    persist them so an audit can rerun the math.
    """

    __tablename__ = "braid_calibration_events"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("braid_decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability_name: Mapped[str] = mapped_column(String(128), nullable=False)
    stated_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_outcome: Mapped[bool] = mapped_column(Boolean, nullable=False)
    log_update: Mapped[float | None] = mapped_column(Float, nullable=True)
    reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback_source: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "lawyer", "admin", "auto"
    feedback_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class BraidDisagreementObservation(Base):
    """One row per multi-run consensus check.

    When a single capability is invoked multiple times for the same
    semantic input (e.g. the same case, same mark, same Nice classes),
    we compute the coefficient of variation across the numeric signals
    in the results. CV > 0.6 (paper threshold) trips an escalation
    flag — the case lands in the admin's "needs review" queue.
    """

    __tablename__ = "braid_disagreement_observations"

    capability_name: Mapped[str] = mapped_column(String(128), nullable=False)
    grouping_key: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        index=True,
        comment="user_message tag (e.g. 'case:<id>') used to bucket samples",
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean: Mapped[float] = mapped_column(Float, nullable=False)
    std_dev: Mapped[float] = mapped_column(Float, nullable=False)
    coefficient_of_variation: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    escalation_triggered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    escalation_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.6
    )
    decision_ids: Mapped[list[Any]] = mapped_column(_JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class BraidBudgetState(Base):
    """Single-row table tracking the rolling daily call budget.

    The bounded-learning paper recommends skipping low-weight
    capabilities when the system is calm so cheap mistakes don't burn
    the budget for genuinely novel cases. ``calls_used`` is reset
    when the rolling window expires (24h). ``skip_threshold`` is the
    minimum capability weight required to run when the budget is
    >= 80% consumed.
    """

    __tablename__ = "braid_budget_state"

    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    daily_call_budget: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000
    )
    calls_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    calls_skipped_under_pressure: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    skip_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.2
    )
    pressure_threshold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.8,
        comment="When calls_used/daily_call_budget exceeds this, "
        "the budget gate starts skipping low-weight caps",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BraidCapabilityWeight(Base):
    """Bayesian-style confidence per capability.

    Updated after every capability invocation: ``weight`` is a posterior
    success probability clamped between ``weight_floor`` and
    ``weight_ceiling``. ``successes``/``failures`` carry the raw counts
    so we can recompute or expose calibration on demand. The reasoning
    side reads ``weight`` to decide whether a low-confidence capability
    should be skipped under the budget threshold.
    """

    __tablename__ = "braid_capability_weights"

    capability_name: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    weight_floor: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.05
    )
    weight_ceiling: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.95
    )
    successes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failures: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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

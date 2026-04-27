"""Bounded online learning layer for BRAID capabilities.

Implements the second face of the BRAID paper (online weight updates
with bounded perturbation) for Etornie's reasoning audit pipeline.

What this module owns
---------------------

* **Weights table**: ``braid_capability_weights`` — one row per
  capability with a Bayesian posterior success probability clamped to
  [floor, ceiling]. Updated after every audited capability call.
* **Update kernel**: a log-update with hard clamps at ±2 (prevent
  exponential explosion when one capability has a long failure streak).
* **Read API**: callers fetch a snapshot for the dashboard /
  ``GET /braid/weights`` endpoint.

What this module does NOT own (left for follow-ups)
----------------------------------------------------

* Calibration tracking (stated_confidence vs actual outcome)
* Disagreement-as-signal (CV across multi-runs)
* Computational budget gating (skip low-weight capabilities when
  daily call budget is tight)

Each of those needs its own table and is a separate sprint.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.braid.models import BraidCapabilityWeight

logger = logging.getLogger(__name__)

# Hard clamps on the per-step log-odds update — keeps a single
# pathological capability run from collapsing the weight to 0 or
# overshooting to 1. Spec value from the paper / reference cortex
# implementation: log-update clamp [-2, 2], reward clamp [-1, 1].
LOG_UPDATE_CLAMP = 2.0
REWARD_CLAMP = 1.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _logit(p: float) -> float:
    p = _clamp(p, 1e-6, 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _bayesian_step(
    *, current_weight: float, success: bool, learning_rate: float = 0.5
) -> float:
    """Apply one log-update step.

    The reward is +1 for a successful capability call, −1 for a
    failure. ``learning_rate`` scales the magnitude before clamping —
    smaller values mean each call moves the weight less, which is the
    pattern the paper recommends so a single noisy outcome can't flip
    the prior. Both reward and log-update get hard clamps.
    """
    reward = 1.0 if success else -1.0
    reward = _clamp(reward, -REWARD_CLAMP, REWARD_CLAMP)
    raw_update = learning_rate * reward
    update = _clamp(raw_update, -LOG_UPDATE_CLAMP, LOG_UPDATE_CLAMP)
    new_logit = _logit(current_weight) + update
    return _sigmoid(new_logit)


async def _get_or_create_weight(
    db: AsyncSession, capability_name: str
) -> BraidCapabilityWeight:
    row = (
        await db.execute(
            select(BraidCapabilityWeight).where(
                BraidCapabilityWeight.capability_name == capability_name
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = BraidCapabilityWeight(capability_name=capability_name)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def update_weight_from_outcome(
    db: AsyncSession,
    *,
    capability_name: str,
    success: bool,
    decided_at: datetime | None = None,
) -> BraidCapabilityWeight:
    """Update the weight row for ``capability_name`` with one outcome.

    Best-effort: callers run this from inside :mod:`app.braid.internal`
    and any failure here is logged but never propagated — the actual
    capability result has already returned to the caller and we don't
    want a learning bug to break the user-visible flow.
    """
    weight_row = await _get_or_create_weight(db, capability_name)
    new_weight = _bayesian_step(
        current_weight=weight_row.weight, success=success
    )
    weight_row.weight = _clamp(
        new_weight, weight_row.weight_floor, weight_row.weight_ceiling
    )
    if success:
        weight_row.successes += 1
    else:
        weight_row.failures += 1
    weight_row.last_decision_at = decided_at or datetime.now(timezone.utc)
    await db.flush()
    return weight_row


async def list_weights(
    db: AsyncSession, *, capability_names: Iterable[str] | None = None
) -> list[BraidCapabilityWeight]:
    """Return all weight rows, optionally filtered by name."""
    stmt = select(BraidCapabilityWeight).order_by(
        BraidCapabilityWeight.capability_name
    )
    if capability_names is not None:
        names = list(capability_names)
        if names:
            stmt = stmt.where(
                BraidCapabilityWeight.capability_name.in_(names)
            )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


# ────────────────────────────────────────────────────────────────────
# Feedback → calibration events
# ────────────────────────────────────────────────────────────────────


def _extract_stated_confidence(result: dict[str, Any] | None) -> float | None:
    """Pull the confidence the capability self-reported, if any.

    Different capabilities expose this under different keys (we look
    at ``confidence``, ``risk_level`` translated to a 0..1 ladder, and
    ``completeness_pct``). Returns None if no recognised field.
    """
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("confidence"), (int, float)):
        return _clamp(float(result["confidence"]), 0.0, 1.0)
    risk = result.get("risk_level")
    if isinstance(risk, str):
        # Inverted: low risk → high confidence in "no conflict".
        ladder = {"none": 0.95, "low": 0.8, "medium": 0.5, "high": 0.2, "exact": 0.05}
        if risk in ladder:
            return ladder[risk]
    if isinstance(result.get("completeness_pct"), (int, float)):
        return _clamp(float(result["completeness_pct"]), 0.0, 1.0)
    return None


async def record_feedback(
    db: AsyncSession,
    *,
    decision_id: uuid.UUID,
    actual_outcome: bool,
    feedback_source: str,
    feedback_user_id: uuid.UUID | None,
    notes: str | None = None,
) -> "BraidCalibrationEvent":
    """Persist lawyer/admin feedback against a BraidDecision.

    Side-effects:
      * Creates a ``BraidCalibrationEvent`` row.
      * Re-applies a Bayesian update to the capability weight using
        the ground-truth outcome (overrides the optimistic "no error
        means success" signal we used when the decision was first
        recorded).

    Raises ``ValueError`` if the decision doesn't exist.
    """
    from app.braid.models import (
        BraidCalibrationEvent,
        BraidDecision,
    )

    decision = await db.get(BraidDecision, decision_id)
    if decision is None:
        raise ValueError(f"decision {decision_id} not found")

    stated = _extract_stated_confidence(decision.result)
    reward = _clamp(1.0 if actual_outcome else -1.0, -REWARD_CLAMP, REWARD_CLAMP)
    log_update = _clamp(0.5 * reward, -LOG_UPDATE_CLAMP, LOG_UPDATE_CLAMP)

    event = BraidCalibrationEvent(
        decision_id=decision.id,
        capability_name=decision.capability_name,
        stated_confidence=stated,
        actual_outcome=actual_outcome,
        log_update=log_update,
        reward=reward,
        feedback_source=feedback_source,
        feedback_user_id=feedback_user_id,
        notes=notes,
    )
    db.add(event)
    await db.flush()

    # Apply the bounded update to the capability weight.
    await update_weight_from_outcome(
        db,
        capability_name=decision.capability_name,
        success=actual_outcome,
    )
    await db.refresh(event)
    return event


async def list_calibration_events(
    db: AsyncSession,
    *,
    capability_name: str | None = None,
    limit: int = 200,
) -> list["BraidCalibrationEvent"]:
    from app.braid.models import BraidCalibrationEvent
    from sqlalchemy import desc

    stmt = select(BraidCalibrationEvent).order_by(
        desc(BraidCalibrationEvent.created_at)
    )
    if capability_name:
        stmt = stmt.where(
            BraidCalibrationEvent.capability_name == capability_name
        )
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


def calibration_summary(
    events: Iterable["BraidCalibrationEvent"],
) -> dict[str, dict[str, Any]]:
    """Aggregate calibration-error per capability from a list of events.

    Returns a dict keyed by capability_name with the count, mean
    stated confidence, observed accuracy, and absolute calibration
    error (|stated − accuracy|). Empty if no events.
    """
    by_cap: dict[str, list[Any]] = {}
    for ev in events:
        by_cap.setdefault(ev.capability_name, []).append(ev)
    summary: dict[str, dict[str, Any]] = {}
    for cap, items in by_cap.items():
        total = len(items)
        correct = sum(1 for e in items if e.actual_outcome)
        with_stated = [e for e in items if e.stated_confidence is not None]
        mean_stated = (
            sum(e.stated_confidence for e in with_stated) / len(with_stated)
            if with_stated
            else None
        )
        accuracy = correct / total if total else 0.0
        error = (
            abs(mean_stated - accuracy) if mean_stated is not None else None
        )
        summary[cap] = {
            "events": total,
            "correct": correct,
            "accuracy": accuracy,
            "mean_stated_confidence": mean_stated,
            "calibration_error": error,
        }
    return summary


# ────────────────────────────────────────────────────────────────────
# Disagreement detector
# ────────────────────────────────────────────────────────────────────


_DISAGREEMENT_NUMERIC_KEYS = (
    "confidence",
    "completeness_pct",
    "match_count",
)


def _extract_numeric_signal(result: dict[str, Any] | None) -> float | None:
    """Best-effort numeric extraction for disagreement clustering.

    Different capabilities expose different scalars; we walk a
    priority list and take the first numeric we find. Returns None
    when no signal is present (those decisions are excluded from
    disagreement aggregation).
    """
    if not isinstance(result, dict):
        return None
    for key in _DISAGREEMENT_NUMERIC_KEYS:
        if isinstance(result.get(key), (int, float)):
            return float(result[key])
    risk = result.get("risk_level")
    if isinstance(risk, str):
        ladder = {"none": 0.0, "low": 0.25, "medium": 0.5, "high": 0.75, "exact": 1.0}
        if risk in ladder:
            return ladder[risk]
    return None


async def evaluate_disagreement(
    db: AsyncSession,
    *,
    capability_name: str,
    grouping_key: str,
    escalation_threshold: float = 0.6,
) -> "BraidDisagreementObservation | None":
    """Compute coefficient-of-variation across all decisions for one bucket.

    ``grouping_key`` is the BraidDecision.user_message tag (e.g.
    ``case:<uuid>``). We pull every decision in that bucket, extract
    the numeric signal, compute mean + std, and persist a row. If CV
    > ``escalation_threshold`` we also flip the escalation flag on.

    Returns None if there are fewer than 2 decisions with extractable
    signals (no disagreement to compute).
    """
    from sqlalchemy import desc

    from app.braid.models import (
        BraidDecision,
        BraidDisagreementObservation,
    )

    stmt = (
        select(BraidDecision)
        .where(
            BraidDecision.capability_name == capability_name,
            BraidDecision.user_message.is_not(None),
            BraidDecision.user_message.contains(grouping_key),
        )
        .order_by(desc(BraidDecision.created_at))
    )
    rows = (await db.execute(stmt)).scalars().all()
    samples: list[tuple[uuid.UUID, float]] = []
    for r in rows:
        sig = _extract_numeric_signal(r.result)
        if sig is None:
            continue
        samples.append((r.id, sig))
    if len(samples) < 2:
        return None
    values = [s[1] for s in samples]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std_dev = math.sqrt(variance)
    cv = (std_dev / abs(mean)) if abs(mean) > 1e-9 else 0.0
    escalate = cv > escalation_threshold

    obs = BraidDisagreementObservation(
        capability_name=capability_name,
        grouping_key=grouping_key,
        sample_count=len(samples),
        mean=mean,
        std_dev=std_dev,
        coefficient_of_variation=cv,
        escalation_triggered=escalate,
        escalation_threshold=escalation_threshold,
        decision_ids=[str(s[0]) for s in samples],
    )
    db.add(obs)
    await db.flush()
    await db.refresh(obs)
    return obs


async def list_disagreement_observations(
    db: AsyncSession,
    *,
    capability_name: str | None = None,
    only_escalated: bool = False,
    limit: int = 200,
) -> list["BraidDisagreementObservation"]:
    from sqlalchemy import desc

    from app.braid.models import BraidDisagreementObservation

    stmt = select(BraidDisagreementObservation).order_by(
        desc(BraidDisagreementObservation.created_at)
    )
    if capability_name:
        stmt = stmt.where(
            BraidDisagreementObservation.capability_name == capability_name
        )
    if only_escalated:
        stmt = stmt.where(
            BraidDisagreementObservation.escalation_triggered.is_(True)
        )
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


# ────────────────────────────────────────────────────────────────────
# Computational budget
# ────────────────────────────────────────────────────────────────────


async def _get_or_create_budget(
    db: AsyncSession, *, daily_budget: int = 1000
) -> "BraidBudgetState":
    """Fetch the (single-row) budget record, creating it on first use."""
    from app.braid.models import BraidBudgetState

    row = (
        await db.execute(select(BraidBudgetState).limit(1))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = BraidBudgetState(
            window_start=now,
            window_end=now + timedelta(days=1),
            daily_call_budget=daily_budget,
            calls_used=0,
            calls_skipped_under_pressure=0,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row
    # Roll the window forward when expired so the budget naturally
    # resets each calendar day. SQLite (used in tests) strips tzinfo
    # on roundtrip, so we coerce the column value to UTC-aware before
    # comparing.
    window_end = row.window_end
    if window_end is not None and window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    if window_end is not None and window_end < now:
        row.window_start = now
        row.window_end = now + timedelta(days=1)
        row.calls_used = 0
        row.calls_skipped_under_pressure = 0
        await db.flush()
    return row


async def consume_budget(
    db: AsyncSession,
    *,
    capability_name: str,
) -> tuple[bool, "BraidBudgetState"]:
    """Decide whether ``capability_name`` is allowed to run right now.

    Returns ``(allowed, budget_row)``. The decision rule:

    * If the rolling window has remaining budget AND
      (pressure < pressure_threshold OR weight >= skip_threshold),
      allow → increment ``calls_used``.
    * Otherwise deny → increment ``calls_skipped_under_pressure``.

    Either way the budget row is returned so callers / endpoints can
    see how close to the cap we are.
    """
    budget = await _get_or_create_budget(db)
    weight_row = await _get_or_create_weight(db, capability_name)
    pressure = (
        budget.calls_used / budget.daily_call_budget
        if budget.daily_call_budget > 0
        else 1.0
    )

    if budget.calls_used >= budget.daily_call_budget:
        budget.calls_skipped_under_pressure += 1
        await db.flush()
        return False, budget

    if pressure >= budget.pressure_threshold and weight_row.weight < budget.skip_threshold:
        budget.calls_skipped_under_pressure += 1
        await db.flush()
        return False, budget

    budget.calls_used += 1
    await db.flush()
    return True, budget


async def get_budget_state(db: AsyncSession) -> "BraidBudgetState":
    """Return the live budget row (initialising if absent)."""
    return await _get_or_create_budget(db)

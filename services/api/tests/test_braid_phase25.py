"""Tests for BRAID Phase 2.5 — feedback / calibration / disagreement / budget.

Each layer is wired into the same in-process call path so we test it
end-to-end with the real `_audit` + bounded-learning loop. We patch
only the LLM-bound capability handlers so the tests don't depend on
network or Together AI; everything else (DB rows, weight rolls, audit
linkage, disagreement clustering, budget gate) runs for real.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.braid.internal import BraidCapabilityError, call_capability
from app.braid.learning import (
    _extract_numeric_signal,
    _extract_stated_confidence,
    calibration_summary,
    consume_budget,
    evaluate_disagreement,
    get_budget_state,
    list_calibration_events,
    list_disagreement_observations,
    record_feedback,
)
from app.braid.models import (
    BraidBudgetState,
    BraidCalibrationEvent,
    BraidDecision,
    BraidDisagreementObservation,
)
from app.users.models import User


@pytest.fixture(autouse=True)
def _braid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "braid_internal_token", "test-token")


# ────────────────────────────────────────────────────────────────────
# stated-confidence + numeric-signal extractors
# ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "result, expected",
    [
        ({"confidence": 0.83}, 0.83),
        ({"confidence": 1.7}, 1.0),  # clamped
        ({"completeness_pct": 0.6}, 0.6),
        ({"risk_level": "none"}, 0.95),
        ({"risk_level": "high"}, 0.2),
        ({"risk_level": "exact"}, 0.05),
        ({}, None),
        (None, None),
        ({"unrelated": True}, None),
    ],
)
def test_extract_stated_confidence(result, expected) -> None:
    assert _extract_stated_confidence(result) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "result, expected",
    [
        ({"confidence": 0.4}, 0.4),
        ({"completeness_pct": 0.9}, 0.9),
        ({"match_count": 7}, 7.0),
        ({"risk_level": "low"}, 0.25),
        ({}, None),
        (None, None),
    ],
)
def test_extract_numeric_signal(result, expected) -> None:
    assert _extract_numeric_signal(result) == expected


# ────────────────────────────────────────────────────────────────────
# Feedback → calibration event
# ────────────────────────────────────────────────────────────────────


async def _seed_decision(
    db: AsyncSession, capability: str, result: dict | None = None
) -> uuid.UUID:
    """Persist a synthetic BraidDecision so feedback has something to attach to.

    Async because the SQLAlchemy ``default=uuid.uuid4`` only fires on
    flush — we must flush before the id is meaningful.
    """
    started = datetime.now(timezone.utc)
    decision = BraidDecision(
        workspace_id="internal",
        thread_id=0,
        agent_id=0,
        agent_name="etornie-internal",
        capability_name=capability,
        args={"x": 1},
        result=result,
        error=None,
        user_message=None,
        started_at=started,
        completed_at=started,
        duration_ms=10,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)
    return decision.id


@pytest.mark.integration
async def test_record_feedback_creates_event_and_updates_weight(
    db_session: AsyncSession, lawyer_user: User
) -> None:
    decision_id = await _seed_decision(
        db_session,
        capability="validate_nice_classification",
        result={"confidence": 0.7},
    )

    event = await record_feedback(
        db_session,
        decision_id=decision_id,
        actual_outcome=True,
        feedback_source="lawyer",
        feedback_user_id=lawyer_user.id,
        notes="lawyer confirmed correct classification",
    )
    assert event.actual_outcome is True
    assert event.stated_confidence == pytest.approx(0.7)
    assert event.reward == pytest.approx(1.0)
    assert event.log_update == pytest.approx(0.5)
    assert event.feedback_source == "lawyer"
    assert event.feedback_user_id == lawyer_user.id

    # The weight row for the capability must now reflect the success.
    from app.braid.learning import list_weights

    rows = await list_weights(
        db_session, capability_names=["validate_nice_classification"]
    )
    assert rows and rows[0].weight > 0.5
    assert rows[0].successes >= 1


@pytest.mark.integration
async def test_record_feedback_rejects_unknown_decision(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="not found"):
        await record_feedback(
            db_session,
            decision_id=uuid.uuid4(),
            actual_outcome=True,
            feedback_source="lawyer",
            feedback_user_id=None,
        )


@pytest.mark.integration
async def test_calibration_summary_aggregates_per_capability(
    db_session: AsyncSession, lawyer_user: User
) -> None:
    # Seed 2 decisions for capA (one correct, one incorrect),
    # 1 decision for capB (correct).
    a1 = await _seed_decision(db_session, "capA", {"confidence": 0.9})
    a2 = await _seed_decision(db_session, "capA", {"confidence": 0.4})
    b1 = await _seed_decision(db_session, "capB", {"confidence": 0.7})

    await record_feedback(
        db_session,
        decision_id=a1,
        actual_outcome=True,
        feedback_source="lawyer",
        feedback_user_id=lawyer_user.id,
    )
    await record_feedback(
        db_session,
        decision_id=a2,
        actual_outcome=False,
        feedback_source="lawyer",
        feedback_user_id=lawyer_user.id,
    )
    await record_feedback(
        db_session,
        decision_id=b1,
        actual_outcome=True,
        feedback_source="lawyer",
        feedback_user_id=lawyer_user.id,
    )

    events = await list_calibration_events(db_session)
    summary = calibration_summary(events)
    assert summary["capA"]["events"] == 2
    assert summary["capA"]["correct"] == 1
    assert summary["capA"]["accuracy"] == 0.5
    assert summary["capA"]["mean_stated_confidence"] == pytest.approx(0.65)
    assert summary["capA"]["calibration_error"] == pytest.approx(0.15, abs=1e-9)
    assert summary["capB"]["accuracy"] == 1.0


# ────────────────────────────────────────────────────────────────────
# Disagreement detector
# ────────────────────────────────────────────────────────────────────


async def _seed_decision_with_message(
    db: AsyncSession,
    capability: str,
    result: dict,
    user_message: str,
) -> uuid.UUID:
    started = datetime.now(timezone.utc)
    decision = BraidDecision(
        workspace_id="internal",
        thread_id=0,
        agent_id=0,
        agent_name="etornie-internal",
        capability_name=capability,
        args={},
        result=result,
        error=None,
        user_message=user_message,
        started_at=started,
        completed_at=started,
        duration_ms=10,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)
    return decision.id


@pytest.mark.integration
async def test_disagreement_skips_when_too_few_samples(
    db_session: AsyncSession,
) -> None:
    case_id = uuid.uuid4()
    await _seed_decision_with_message(
        db_session,
        "check_trademark_conflict",
        {"confidence": 0.5},
        f"case:{case_id}",
    )

    obs = await evaluate_disagreement(
        db_session,
        capability_name="check_trademark_conflict",
        grouping_key=f"case:{case_id}",
    )
    assert obs is None


@pytest.mark.integration
async def test_disagreement_flags_high_cv(
    db_session: AsyncSession,
) -> None:
    case_id = uuid.uuid4()
    # Two wildly disagreeing runs → CV very high → escalation_triggered=True
    await _seed_decision_with_message(
        db_session,
        "check_trademark_conflict",
        {"confidence": 0.05},
        f"case:{case_id}",
    )
    await _seed_decision_with_message(
        db_session,
        "check_trademark_conflict",
        {"confidence": 0.95},
        f"case:{case_id}",
    )

    obs = await evaluate_disagreement(
        db_session,
        capability_name="check_trademark_conflict",
        grouping_key=f"case:{case_id}",
    )
    assert obs is not None
    assert obs.sample_count == 2
    assert obs.escalation_triggered is True
    assert obs.coefficient_of_variation > 0.6


@pytest.mark.integration
async def test_disagreement_low_cv_does_not_escalate(
    db_session: AsyncSession,
) -> None:
    case_id = uuid.uuid4()
    await _seed_decision_with_message(
        db_session,
        "score_document_completeness",
        {"completeness_pct": 0.79},
        f"case:{case_id}",
    )
    await _seed_decision_with_message(
        db_session,
        "score_document_completeness",
        {"completeness_pct": 0.81},
        f"case:{case_id}",
    )

    obs = await evaluate_disagreement(
        db_session,
        capability_name="score_document_completeness",
        grouping_key=f"case:{case_id}",
    )
    assert obs is not None
    assert obs.escalation_triggered is False


@pytest.mark.integration
async def test_list_disagreement_filters_only_escalated(
    db_session: AsyncSession,
) -> None:
    case_a, case_b = uuid.uuid4(), uuid.uuid4()
    await _seed_decision_with_message(
        db_session, "cap", {"confidence": 0.05}, f"case:{case_a}"
    )
    await _seed_decision_with_message(
        db_session, "cap", {"confidence": 0.95}, f"case:{case_a}"
    )
    await _seed_decision_with_message(
        db_session, "cap", {"confidence": 0.5}, f"case:{case_b}"
    )
    await _seed_decision_with_message(
        db_session, "cap", {"confidence": 0.51}, f"case:{case_b}"
    )

    await evaluate_disagreement(
        db_session, capability_name="cap", grouping_key=f"case:{case_a}"
    )
    await evaluate_disagreement(
        db_session, capability_name="cap", grouping_key=f"case:{case_b}"
    )

    all_rows = await list_disagreement_observations(db_session)
    assert len(all_rows) == 2
    escalated = await list_disagreement_observations(
        db_session, only_escalated=True
    )
    assert len(escalated) == 1
    assert escalated[0].grouping_key == f"case:{case_a}"


# ────────────────────────────────────────────────────────────────────
# Computational budget
# ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_budget_initialises_with_defaults(
    db_session: AsyncSession,
) -> None:
    state = await get_budget_state(db_session)
    assert state.calls_used == 0
    assert state.daily_call_budget > 0
    assert 0 < state.skip_threshold < 1
    assert 0 < state.pressure_threshold < 1


@pytest.mark.integration
async def test_consume_budget_allows_when_under_pressure(
    db_session: AsyncSession,
) -> None:
    allowed, state = await consume_budget(
        db_session, capability_name="capA"
    )
    assert allowed
    assert state.calls_used == 1
    assert state.calls_skipped_under_pressure == 0


@pytest.mark.integration
async def test_consume_budget_skips_low_weight_under_pressure(
    db_session: AsyncSession,
) -> None:
    """Force the budget into >= pressure_threshold and verify a low-weight
    capability is denied while a high-weight one still runs."""
    state = await get_budget_state(db_session)
    # Set a tiny budget so a couple of calls reach the threshold quickly.
    state.daily_call_budget = 10
    state.calls_used = 9  # 90% pressure → above default 80%
    await db_session.flush()

    # Seed two capability weights — one well below skip_threshold, one above.
    from app.braid.learning import _get_or_create_weight

    low = await _get_or_create_weight(db_session, "low_cap")
    low.weight = 0.05  # below skip_threshold (0.2)
    high = await _get_or_create_weight(db_session, "high_cap")
    high.weight = 0.9
    await db_session.flush()

    allowed_low, _ = await consume_budget(db_session, capability_name="low_cap")
    allowed_high, _ = await consume_budget(db_session, capability_name="high_cap")

    assert allowed_low is False
    assert allowed_high is True

    final = await get_budget_state(db_session)
    assert final.calls_skipped_under_pressure >= 1


@pytest.mark.integration
async def test_consume_budget_hard_caps_at_daily_budget(
    db_session: AsyncSession,
) -> None:
    state = await get_budget_state(db_session)
    state.daily_call_budget = 3
    state.calls_used = 3
    await db_session.flush()

    allowed, _ = await consume_budget(db_session, capability_name="any_cap")
    assert allowed is False


@pytest.mark.integration
async def test_budget_window_rolls_after_expiry(
    db_session: AsyncSession,
) -> None:
    state = await get_budget_state(db_session)
    past = datetime.now(timezone.utc) - timedelta(days=2)
    state.window_start = past
    state.window_end = past + timedelta(days=1)
    state.calls_used = 999
    state.calls_skipped_under_pressure = 50
    await db_session.flush()

    rolled = await get_budget_state(db_session)
    assert rolled.calls_used == 0
    assert rolled.calls_skipped_under_pressure == 0
    assert rolled.window_end > datetime.now(timezone.utc)


# ────────────────────────────────────────────────────────────────────
# call_capability with budget gate (end-to-end)
# ────────────────────────────────────────────────────────────────────


class _FakeRequest(BaseModel):
    x: int


class _FakeResponse(BaseModel):
    confidence: float


@pytest.mark.integration
async def test_call_capability_skipped_when_budget_denies(
    db_session: AsyncSession,
) -> None:
    state = await get_budget_state(db_session)
    state.daily_call_budget = 1
    state.calls_used = 1  # already at cap
    await db_session.flush()

    handler = AsyncMock(return_value=_FakeResponse(confidence=0.9))
    with pytest.raises(BraidCapabilityError) as exc_info:
        await call_capability(
            db_session,
            capability_name="any_cap",
            request=_FakeRequest(x=1),
            handler=handler,
        )
    assert exc_info.value.status_code == 429
    handler.assert_not_called()

    # An audit row was still written documenting the skip.
    rows = (
        await db_session.execute(
            select(BraidDecision).where(
                BraidDecision.capability_name == "any_cap"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].error and "skipped" in rows[0].error


@pytest.mark.integration
async def test_call_capability_runs_disagreement_eval_on_success(
    db_session: AsyncSession,
) -> None:
    """When user_message carries a `case:<id>` token, _audit kicks off
    the disagreement evaluator. After 2 successful runs we should see
    a BraidDisagreementObservation row for that case."""
    case_id = uuid.uuid4()

    handler = AsyncMock(side_effect=[
        _FakeResponse(confidence=0.1),
        _FakeResponse(confidence=0.9),
    ])
    for _ in range(2):
        await call_capability(
            db_session,
            capability_name="check_trademark_conflict",
            request=_FakeRequest(x=1),
            handler=handler,
            user_message=f"case:{case_id}",
        )

    obs_rows = (
        await db_session.execute(select(BraidDisagreementObservation))
    ).scalars().all()
    assert any(r.grouping_key == f"case:{case_id}" for r in obs_rows)

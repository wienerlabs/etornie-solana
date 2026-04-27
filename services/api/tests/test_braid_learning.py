"""Tests for the BRAID bounded-learning weight layer."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.braid.learning import (
    LOG_UPDATE_CLAMP,
    REWARD_CLAMP,
    _bayesian_step,
    _clamp,
    _logit,
    _sigmoid,
    list_weights,
    update_weight_from_outcome,
)


@pytest.mark.unit
def test_clamp_constants_match_spec() -> None:
    """Reference cortex implementation locks these values; if either
    drifts the bounded-learning kernel is no longer 'bounded'."""
    assert LOG_UPDATE_CLAMP == 2.0
    assert REWARD_CLAMP == 1.0


@pytest.mark.unit
def test_clamp_basic() -> None:
    assert _clamp(0.5, 0.1, 0.9) == 0.5
    assert _clamp(-1, 0.1, 0.9) == 0.1
    assert _clamp(99, 0.1, 0.9) == 0.9


@pytest.mark.unit
def test_logit_sigmoid_round_trip() -> None:
    for p in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert pytest.approx(p, abs=1e-9) == _sigmoid(_logit(p))


@pytest.mark.unit
def test_bayesian_step_moves_weight_toward_reward() -> None:
    """Successful outcomes pull the weight up; failures pull it down."""
    up = _bayesian_step(current_weight=0.5, success=True)
    down = _bayesian_step(current_weight=0.5, success=False)
    assert up > 0.5
    assert down < 0.5
    # Symmetry: equal & opposite around 0.5 because the log-update is
    # ±LR and we start at logit=0
    assert pytest.approx(up + down, abs=1e-9) == 1.0


@pytest.mark.unit
def test_bayesian_step_respects_clamp() -> None:
    """Even with a giant LR, log-update is hard-clamped to ±2 so a
    single bad outcome can't crash the weight to 0."""
    moved = _bayesian_step(current_weight=0.5, success=False, learning_rate=10.0)
    # post-clamp: logit(0.5)=0 → -2 → sigmoid(-2) ≈ 0.119
    assert pytest.approx(moved, abs=1e-3) == 0.1192


@pytest.mark.integration
async def test_update_creates_row_with_default_weight(
    db_session: AsyncSession,
) -> None:
    row = await update_weight_from_outcome(
        db_session, capability_name="ping", success=True
    )
    assert row.capability_name == "ping"
    assert row.successes == 1
    assert row.failures == 0
    assert row.weight > 0.5
    assert row.weight <= row.weight_ceiling


@pytest.mark.integration
async def test_repeated_failures_cannot_breach_floor(
    db_session: AsyncSession,
) -> None:
    """Run 50 consecutive failures — the floor clamp must hold."""
    for _ in range(50):
        await update_weight_from_outcome(
            db_session, capability_name="check_trademark_conflict", success=False
        )
    rows = await list_weights(db_session, capability_names=["check_trademark_conflict"])
    assert len(rows) == 1
    assert rows[0].weight >= rows[0].weight_floor
    assert rows[0].failures == 50
    assert rows[0].successes == 0


@pytest.mark.integration
async def test_repeated_successes_cannot_breach_ceiling(
    db_session: AsyncSession,
) -> None:
    for _ in range(50):
        await update_weight_from_outcome(
            db_session, capability_name="validate_nice_classification", success=True
        )
    rows = await list_weights(db_session, capability_names=["validate_nice_classification"])
    assert len(rows) == 1
    assert rows[0].weight <= rows[0].weight_ceiling
    assert rows[0].successes == 50


@pytest.mark.integration
async def test_list_weights_returns_all_when_unfiltered(
    db_session: AsyncSession,
) -> None:
    await update_weight_from_outcome(db_session, capability_name="a", success=True)
    await update_weight_from_outcome(db_session, capability_name="b", success=False)
    rows = await list_weights(db_session)
    assert {r.capability_name for r in rows} == {"a", "b"}


@pytest.mark.integration
async def test_internal_call_capability_updates_weights(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a successful call_capability run audits AND bumps the weight."""
    from unittest.mock import AsyncMock

    from app.braid.internal import call_capability
    from app.config import settings
    from pydantic import BaseModel

    monkeypatch.setattr(settings, "braid_internal_token", "test-token")

    class FakeRequest(BaseModel):
        x: int

    class FakeResponse(BaseModel):
        ok: bool

    handler = AsyncMock(return_value=FakeResponse(ok=True))
    await call_capability(
        db_session,
        capability_name="fake_capability",
        request=FakeRequest(x=1),
        handler=handler,
    )

    rows = await list_weights(db_session, capability_names=["fake_capability"])
    assert len(rows) == 1
    assert rows[0].successes == 1
    assert rows[0].failures == 0
    assert rows[0].weight > 0.5

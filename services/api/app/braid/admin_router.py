"""Admin-facing BRAID audit endpoints.

Separate from the BRAID-internal endpoints in ``router.py``: those use the
shared ``X-Braid-Auth`` header (BRAID agent → API), while these use the
dashboard's existing JWT auth and require the ``admin`` role. They expose
the same underlying audit data so admins can browse BRAID decisions from
the Etornie dashboard without the BRAID agent's bearer token leaking to
the browser.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.auth.dependencies import require_role
from app.braid.learning import (
    calibration_summary,
    get_budget_state,
    list_calibration_events,
    list_disagreement_observations,
    list_weights,
    record_feedback,
)
from app.braid.models import (
    BraidBudgetState,
    BraidCalibrationEvent,
    BraidCapabilityWeight,
    BraidDecision,
    BraidDisagreementObservation,
)
from app.braid.router import DecisionList, DecisionRow, _row_to_model
from app.database import get_db
from app.users.models import User, UserRole


class CapabilityWeightRow(BaseModel):
    capability_name: str
    weight: float
    weight_floor: float
    weight_ceiling: float
    successes: int
    failures: int
    last_decision_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class CapabilityWeightList(BaseModel):
    items: list[CapabilityWeightRow]
    count: int

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/braid", tags=["braid-admin"])


@router.get(
    "/decisions",
    response_model=DecisionList,
    summary="Admin: list BRAID decisions (newest first) with filters",
)
async def admin_list_decisions(
    workspace_id: str | None = Query(default=None, max_length=64),
    thread_id: int | None = Query(default=None),
    capability_name: str | None = Query(default=None, max_length=128),
    only_errors: bool = Query(
        default=False,
        description="If true, only return decisions where the capability errored",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    stmt = select(BraidDecision).order_by(desc(BraidDecision.started_at))
    if workspace_id is not None:
        stmt = stmt.where(BraidDecision.workspace_id == workspace_id)
    if thread_id is not None:
        stmt = stmt.where(BraidDecision.thread_id == thread_id)
    if capability_name is not None:
        stmt = stmt.where(BraidDecision.capability_name == capability_name)
    if only_errors:
        stmt = stmt.where(BraidDecision.error.is_not(None))
    stmt = stmt.offset(offset).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return DecisionList(
        items=[_row_to_model(r) for r in rows], count=len(rows)
    )


@router.get(
    "/cases/{case_id}/decisions",
    response_model=DecisionList,
    summary=(
        "BRAID decisions tagged with this case via user_message=case:<id>. "
        "Open to admin + lawyer + client of the case (RBAC inside)."
    ),
)
async def case_scoped_decisions(
    case_id: uuid.UUID,
    capability_name: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer, UserRole.client)),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    """Surface BRAID decisions inline on the case detail page.

    Lawyer/client may only see decisions for cases they're attached
    to. Admin sees everything. We filter the audit table by the
    ``user_message`` LIKE 'case:<uuid>' pattern that hooks tag with.
    """
    from app.cases.service import get_case

    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    if current_user.role != UserRole.admin:
        owner_id = getattr(case, "assigned_lawyer_id", None)
        client_id = getattr(case, "client_id", None)
        if current_user.id not in {owner_id, client_id}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

    needle = f"case:{case_id}"
    stmt = (
        select(BraidDecision)
        .where(
            BraidDecision.user_message.is_not(None),
            BraidDecision.user_message.contains(needle),
        )
        .order_by(desc(BraidDecision.started_at))
        .limit(limit)
    )
    if capability_name is not None:
        stmt = stmt.where(BraidDecision.capability_name == capability_name)

    rows = (await db.execute(stmt)).scalars().all()
    return DecisionList(
        items=[_row_to_model(r) for r in rows], count=len(rows)
    )


@router.get(
    "/decisions/trace",
    response_model=DecisionList,
    summary="Admin: chronological trace of decisions for one (workspace, thread)",
)
async def admin_get_trace(
    workspace_id: str = Query(..., max_length=64),
    thread_id: int = Query(...),
    _admin: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    stmt = (
        select(BraidDecision)
        .where(BraidDecision.workspace_id == workspace_id)
        .where(BraidDecision.thread_id == thread_id)
        .order_by(BraidDecision.started_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return DecisionList(
        items=[_row_to_model(r) for r in rows], count=len(rows)
    )


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionRow,
    summary="Admin: single decision detail",
)
async def admin_get_decision(
    decision_id: uuid.UUID,
    _admin: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> DecisionRow:
    row = await db.get(BraidDecision, decision_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"decision {decision_id} not found"
        )
    return _row_to_model(row)


@router.get(
    "/weights",
    response_model=CapabilityWeightList,
    summary="Admin: bounded-learning weights snapshot per capability",
)
async def admin_list_weights(
    _admin: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> CapabilityWeightList:
    rows = await list_weights(db)
    return CapabilityWeightList(
        items=[CapabilityWeightRow.model_validate(r) for r in rows],
        count=len(rows),
    )


# ─────────────────────────────────────────────────────────────────────
# Calibration (feedback events + summary)
# ─────────────────────────────────────────────────────────────────────


class CalibrationEventRow(BaseModel):
    id: uuid.UUID
    decision_id: uuid.UUID
    capability_name: str
    stated_confidence: float | None
    actual_outcome: bool
    log_update: float | None
    reward: float | None
    feedback_source: str
    feedback_user_id: uuid.UUID | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CalibrationCapability(BaseModel):
    capability_name: str
    events: int
    correct: int
    accuracy: float
    mean_stated_confidence: float | None
    calibration_error: float | None


class CalibrationReport(BaseModel):
    items: list[CalibrationEventRow]
    summary: list[CalibrationCapability]
    count: int


@router.get(
    "/calibration",
    response_model=CalibrationReport,
    summary="Admin: calibration events + per-capability summary",
)
async def admin_list_calibration(
    capability_name: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=200, ge=1, le=1000),
    _admin: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> CalibrationReport:
    events = await list_calibration_events(
        db, capability_name=capability_name, limit=limit
    )
    summary_dict = calibration_summary(events)
    summary_rows = [
        CalibrationCapability(capability_name=cap, **stats)
        for cap, stats in sorted(summary_dict.items())
    ]
    return CalibrationReport(
        items=[CalibrationEventRow.model_validate(e) for e in events],
        summary=summary_rows,
        count=len(events),
    )


class FeedbackRequest(BaseModel):
    actual_outcome: bool = Field(
        ..., description="True if the capability's call was correct in hindsight"
    )
    notes: str | None = Field(default=None, max_length=1000)


@router.post(
    "/decisions/{decision_id}/feedback",
    response_model=CalibrationEventRow,
    status_code=status.HTTP_201_CREATED,
    summary="Lawyer/admin grades a BRAID decision → updates calibration + weights",
)
async def admin_record_feedback(
    decision_id: uuid.UUID,
    body: FeedbackRequest,
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
    db: AsyncSession = Depends(get_db),
) -> CalibrationEventRow:
    try:
        event = await record_feedback(
            db,
            decision_id=decision_id,
            actual_outcome=body.actual_outcome,
            feedback_source=current_user.role.value,
            feedback_user_id=current_user.id,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return CalibrationEventRow.model_validate(event)


# ─────────────────────────────────────────────────────────────────────
# Disagreement
# ─────────────────────────────────────────────────────────────────────


class DisagreementRow(BaseModel):
    id: uuid.UUID
    capability_name: str
    grouping_key: str
    sample_count: int
    mean: float
    std_dev: float
    coefficient_of_variation: float
    escalation_triggered: bool
    escalation_threshold: float
    decision_ids: list[Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class DisagreementList(BaseModel):
    items: list[DisagreementRow]
    count: int


@router.get(
    "/disagreement",
    response_model=DisagreementList,
    summary="Admin: disagreement observations (CV across multi-runs)",
)
async def admin_list_disagreement(
    capability_name: str | None = Query(default=None, max_length=128),
    only_escalated: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    _admin: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> DisagreementList:
    rows = await list_disagreement_observations(
        db,
        capability_name=capability_name,
        only_escalated=only_escalated,
        limit=limit,
    )
    return DisagreementList(
        items=[DisagreementRow.model_validate(r) for r in rows],
        count=len(rows),
    )


# ─────────────────────────────────────────────────────────────────────
# Budget
# ─────────────────────────────────────────────────────────────────────


class BudgetState(BaseModel):
    window_start: datetime
    window_end: datetime
    daily_call_budget: int
    calls_used: int
    calls_skipped_under_pressure: int
    skip_threshold: float
    pressure_threshold: float
    pressure: float
    updated_at: datetime


@router.get(
    "/budget",
    response_model=BudgetState,
    summary="Admin: rolling daily compute-budget state",
)
async def admin_get_budget(
    _admin: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> BudgetState:
    row = await get_budget_state(db)
    pressure = (
        row.calls_used / row.daily_call_budget
        if row.daily_call_budget > 0
        else 1.0
    )
    return BudgetState(
        window_start=row.window_start,
        window_end=row.window_end,
        daily_call_budget=row.daily_call_budget,
        calls_used=row.calls_used,
        calls_skipped_under_pressure=row.calls_skipped_under_pressure,
        skip_threshold=row.skip_threshold,
        pressure_threshold=row.pressure_threshold,
        pressure=pressure,
        updated_at=row.updated_at,
    )

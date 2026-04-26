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

from app.auth.dependencies import require_role
from app.braid.models import BraidDecision
from app.braid.router import DecisionList, DecisionRow, _row_to_model
from app.database import get_db
from app.users.models import User, UserRole

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

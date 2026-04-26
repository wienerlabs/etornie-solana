"""Server-side BRAID audit helper.

The OpenServ BRAID agent in ``services/braid`` already writes a
``BraidDecision`` row after every capability invocation it dispatches
(via ``addAuditedCapability`` in ``services/braid/src/audit.ts``). But
parts of Etornie's own backend (e.g. the EtornieGPT chat handler) call
the same domain primitives — like ``verify_payment_tx`` — *directly*,
without ever going through the BRAID agent. Those direct calls would
otherwise stay invisible to the BRAID dashboard.

This helper lets backend code emit an equivalent ``BraidDecision`` row
itself, reusing the same table and the same dashboard. The write is
fire-and-forget: failures are logged but never propagated, so the audit
trail can never block the request path.

Use a workspace_id like ``"etorniegpt-chat"`` (or scoped per user) so
backend-originated rows are visually distinct from BRAID-agent rows in
the dashboard list.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.braid.models import BraidDecision
from app.database import async_session

logger = logging.getLogger(__name__)


async def _write_decision(
    *,
    workspace_id: str,
    thread_id: int,
    agent_id: int,
    agent_name: str | None,
    capability_name: str,
    args: dict[str, Any],
    result: dict[str, Any] | None,
    error: str | None,
    user_message: str | None,
    started_at: datetime,
    completed_at: datetime,
) -> None:
    duration_ms = max(
        0, int((completed_at - started_at).total_seconds() * 1000)
    )
    decision = BraidDecision(
        workspace_id=workspace_id,
        thread_id=thread_id,
        agent_id=agent_id,
        agent_name=agent_name,
        capability_name=capability_name,
        args=args,
        result=result,
        error=error,
        user_message=user_message,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
    )
    async with async_session() as session:
        session.add(decision)
        await session.commit()


def record_decision_async(
    *,
    workspace_id: str,
    capability_name: str,
    args: dict[str, Any],
    result: dict[str, Any] | None,
    error: str | None,
    user_message: str | None,
    started_at: datetime,
    completed_at: datetime,
    thread_id: int = 0,
    agent_id: int = 0,
    agent_name: str | None = None,
) -> None:
    """Schedule a BraidDecision write as a background task.

    Returns immediately. Any failure (DB down, schema mismatch, etc.) is
    logged at warning level and otherwise swallowed — audit is best
    effort and must never break the request path.
    """

    async def _safe() -> None:
        try:
            await _write_decision(
                workspace_id=workspace_id,
                thread_id=thread_id,
                agent_id=agent_id,
                agent_name=agent_name,
                capability_name=capability_name,
                args=args,
                result=result,
                error=error,
                user_message=user_message,
                started_at=started_at,
                completed_at=completed_at,
            )
        except Exception:
            logger.warning(
                "braid audit: failed to record decision capability=%s",
                capability_name,
                exc_info=True,
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_safe())
    except RuntimeError:
        # No running loop (e.g. called from sync test context). Drop
        # silently — audit must not crash the caller.
        pass

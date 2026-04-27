"""In-process BRAID client for backend hooks.

The BRAID HTTP endpoints in :mod:`app.braid.router` are designed to be
called by the OpenServ external agent over the network. Backend code
running inside the same FastAPI process should not pay the cost of an
HTTP round-trip just to talk to itself, so this module exposes the
same capability logic via direct Python function calls — and writes a
``BraidDecision`` audit row for every invocation so the dashboard
audit trail still sees them.

The internal "agent" that owns these decisions is recorded with
``workspace_id="internal"`` and ``agent_id=0`` so admin filters can
distinguish them from real OpenServ-driven calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.braid.models import BraidDecision

logger = logging.getLogger(__name__)


class BraidCapabilityError(Exception):
    """Raised when a BRAID capability declines or errors out.

    Carries the upstream HTTP-style status code so callers that want to
    surface the failure to the API client can map it back to a 4xx/5xx
    response without leaking the BRAID internals.
    """

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


async def _audit(
    db: AsyncSession,
    *,
    capability_name: str,
    args: dict[str, Any],
    result: dict[str, Any] | None,
    error: str | None,
    started_at: datetime,
    completed_at: datetime,
    user_message: str | None = None,
) -> None:
    """Persist a BraidDecision row for an internal capability call.

    Best-effort: a failure here must not mask the actual capability
    result from the caller, so we swallow + log audit-write errors.
    Also updates the bounded-learning weight row for this capability
    in the same transaction — keeps the audit row + weight history
    in lockstep so admin dashboards never see a decision without a
    matching weight update.
    """
    try:
        duration_ms = max(
            int((completed_at - started_at).total_seconds() * 1000), 0
        )
        decision = BraidDecision(
            workspace_id="internal",
            thread_id=0,
            agent_id=0,
            agent_name="etornie-internal",
            capability_name=capability_name,
            args=args,
            result=result,
            error=error,
            user_message=user_message,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        db.add(decision)
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "braid: internal audit write failed for %s: %s",
            capability_name,
            exc,
        )
        return

    try:
        from app.braid.learning import update_weight_from_outcome

        await update_weight_from_outcome(
            db,
            capability_name=capability_name,
            success=error is None,
            decided_at=completed_at,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "braid: weight update failed for %s: %s", capability_name, exc
        )

    # Disagreement aggregation — only when we have a grouping key
    # (e.g. `case:<uuid>`) and the call actually produced a result we
    # can compare against earlier ones. Pure failure rows are skipped
    # because there's no signal to cluster.
    if error is None and user_message:
        try:
            from app.braid.learning import evaluate_disagreement

            for token in user_message.split():
                token = token.strip()
                if not token or ":" not in token:
                    continue
                await evaluate_disagreement(
                    db,
                    capability_name=capability_name,
                    grouping_key=token,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "braid: disagreement eval failed for %s: %s",
                capability_name,
                exc,
            )


async def call_capability(
    db: AsyncSession,
    *,
    capability_name: str,
    request: BaseModel,
    handler,
    user_message: str | None = None,
    handler_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Run a BRAID capability handler in-process and audit the result.

    ``handler`` is the underlying endpoint coroutine (e.g.
    ``app.braid.router.validate_nice_classification``). We call it
    directly with the right keyword arguments — including the auth
    token from settings so the handler's ``_check_auth`` passes.

    On HTTPException we audit the failure and re-raise as
    :class:`BraidCapabilityError` so non-HTTP callers get a single
    exception type to handle.
    """
    from app.config import settings  # local import — avoid cycles

    if not settings.braid_internal_token:
        raise BraidCapabilityError(
            "braid disabled (BRAID_INTERNAL_TOKEN unset)",
            status_code=503,
        )

    # Budget gate: check daily call window + per-capability weight.
    # On deny we still write a "skipped" audit row so the operator
    # sees that the capability was suppressed (rather than silently
    # missing). Skipped calls also feed disagreement evaluation since
    # they tell us "this case has been seen, but we declined to score
    # it again".
    from app.braid.learning import (
        consume_budget,
        evaluate_disagreement,
    )

    started_at = datetime.now(timezone.utc)
    allowed, _budget = await consume_budget(
        db, capability_name=capability_name
    )
    if not allowed:
        completed_at = datetime.now(timezone.utc)
        await _audit(
            db,
            capability_name=capability_name,
            args=request.model_dump(mode="json"),
            result=None,
            error="skipped: budget gate (low capability weight under pressure)",
            started_at=started_at,
            completed_at=completed_at,
            user_message=user_message,
        )
        raise BraidCapabilityError(
            "BRAID skipped this call: budget gate",
            status_code=429,
        )
    try:
        kwargs = dict(handler_kwargs or {})
        kwargs.setdefault("x_braid_auth", settings.braid_internal_token)
        response = await handler(request, **kwargs)
    except HTTPException as exc:
        completed_at = datetime.now(timezone.utc)
        await _audit(
            db,
            capability_name=capability_name,
            args=request.model_dump(mode="json"),
            result=None,
            error=f"HTTP {exc.status_code}: {exc.detail}",
            started_at=started_at,
            completed_at=completed_at,
            user_message=user_message,
        )
        raise BraidCapabilityError(
            str(exc.detail), status_code=exc.status_code
        ) from exc
    except Exception as exc:  # noqa: BLE001
        completed_at = datetime.now(timezone.utc)
        await _audit(
            db,
            capability_name=capability_name,
            args=request.model_dump(mode="json"),
            result=None,
            error=f"{type(exc).__name__}: {exc}",
            started_at=started_at,
            completed_at=completed_at,
            user_message=user_message,
        )
        raise BraidCapabilityError(str(exc)) from exc

    completed_at = datetime.now(timezone.utc)
    result_payload: dict[str, Any] | None
    if isinstance(response, BaseModel):
        result_payload = response.model_dump(mode="json")
    elif isinstance(response, dict):
        result_payload = response
    else:
        result_payload = None
    await _audit(
        db,
        capability_name=capability_name,
        args=request.model_dump(mode="json"),
        result=result_payload,
        error=None,
        started_at=started_at,
        completed_at=completed_at,
        user_message=user_message,
    )
    return response

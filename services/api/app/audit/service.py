"""Audit log writer — append-only record of who did what, when.

Required by GDPR Article 30 (records of processing activities). Every
case / document / notification mutation should call
``log_audit_event`` from the service layer (not from routers — see
issue #30) so background jobs and webhooks are covered too.
"""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLog

logger = logging.getLogger(__name__)


async def log_audit_event(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    action: AuditAction,
    target_type: str,
    target_id: uuid.UUID,
    case_id: uuid.UUID | None = None,
    details: str | None = None,
) -> AuditLog | None:
    """Record a mutation in the append-only audit log.

    Best-effort: the write happens inside a SAVEPOINT
    (``db.begin_nested()``), so a failing audit insert cannot poison
    the caller's outer transaction or roll back the business mutation
    it is recording — mirrors the posture of
    ``app.security.operator_key.log_operator_access``. Returns the
    persisted row, or ``None`` if the write failed (logged at
    WARNING, never raised).
    """
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        case_id=case_id,
        details=details,
    )
    try:
        async with db.begin_nested():
            db.add(entry)
            await db.flush()
    except Exception:  # noqa: BLE001
        logger.warning(
            "audit log write failed action=%s target_type=%s target_id=%s",
            getattr(action, "value", action),
            target_type,
            target_id,
            exc_info=True,
        )
        return None
    await db.refresh(entry)
    return entry


# Backward-compatible name — existing callers (app.cases.service) keep
# working unchanged. New call sites should prefer log_audit_event.
log_cancellation = log_audit_event

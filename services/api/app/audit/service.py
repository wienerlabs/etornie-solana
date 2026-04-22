import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLog


async def log_cancellation(
    db: AsyncSession,
    actor_id: uuid.UUID,
    action: AuditAction,
    target_type: str,
    target_id: uuid.UUID,
    case_id: uuid.UUID | None = None,
    details: str | None = None,
) -> AuditLog:
    """Record a cancellation action in the audit log."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        case_id=case_id,
        details=details,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry

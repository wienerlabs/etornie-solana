"""Audit log writer — append-only record of who did what, when.

Required by GDPR Article 30 (records of processing activities). Every
case / document / notification mutation calls ``log_audit_event`` from
the service layer (not from routers), so background jobs, the agent and
webhooks are covered, not just HTTP requests.

``Actor`` says who performed the mutation. A user acting through the API
is ``Actor.user(id)``. Mutations with no logged-in user are recorded with
an explicit non-user actor type instead of being skipped:

  agent    the EtornieGPT agent, acting on behalf of a user
  webhook  a payment / provider webhook
  system   a scheduled job or other internal process

For the non-user types ``id`` is the account the action ran on behalf of
when there is one (e.g. the case owner), and ``None`` otherwise.
"""
import enum
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLog

logger = logging.getLogger(__name__)


class ActorType(str, enum.Enum):
    user = "user"
    agent = "agent"
    system = "system"
    webhook = "webhook"


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.type is ActorType.user and self.id is None:
            raise ValueError("a user actor needs a user id")

    @classmethod
    def user(cls, user_id: uuid.UUID) -> "Actor":
        return cls(ActorType.user, user_id)

    @classmethod
    def agent(cls, on_behalf_of: uuid.UUID | None = None) -> "Actor":
        return cls(ActorType.agent, on_behalf_of)

    @classmethod
    def webhook(cls, on_behalf_of: uuid.UUID | None = None) -> "Actor":
        return cls(ActorType.webhook, on_behalf_of)

    @classmethod
    def system(cls, on_behalf_of: uuid.UUID | None = None) -> "Actor":
        return cls(ActorType.system, on_behalf_of)


async def log_audit_event(
    db: AsyncSession,
    *,
    actor: Actor | None = None,
    actor_id: uuid.UUID | None = None,
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
    # Temporary compatibility: call sites that still pass ``actor_id`` are
    # treated as user actors. Removed once every caller passes ``actor``.
    if actor is None:
        if actor_id is None:
            raise ValueError("log_audit_event needs an actor")
        actor = Actor.user(actor_id)
      
    entry = AuditLog(
        actor_id=actor.id,
        actor_type=actor.type.value,
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


async def log_cancellation(
    db: AsyncSession,
    actor_id: uuid.UUID,
    action: AuditAction,
    target_type: str,
    target_id: uuid.UUID,
    case_id: uuid.UUID | None = None,
    details: str | None = None,
) -> AuditLog | None:
    """Deprecated: use ``log_audit_event``. Removed once the two cancel
    call sites (cases.service, documents.service) are migrated."""
    return await log_audit_event(
        db,
        actor=Actor.user(actor_id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        case_id=case_id,
        details=details,
    )

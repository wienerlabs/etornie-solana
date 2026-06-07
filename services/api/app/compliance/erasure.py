"""GDPR Article 17 right-to-erasure execution.

Applies the disposition declared in :mod:`app.compliance.retention`:

1. Refuse if the subject has a case in an active legal proceeding
   (Art. 17(3)(e)) — the caller gets the blocking cases back.
2. Physically delete the ``DELETE`` tables (and any backing files on
   disk).
3. Tombstone the ``users`` row so every ``RETAIN`` row that still
   references the user id becomes pseudonymous, and null the invite FKs.

Everything runs on the caller's session inside one transaction; the
request-scoped session dependency commits. The function is idempotent:
erasing an already-erased user is a no-op that returns a zero summary.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import AgentMessage, AgentSession, AgentUpload
from app.auth.utils import hash_password
from app.braid.models import BraidCalibrationEvent
from app.cases.models import Case, CaseNote
from app.compliance import retention
from app.config import settings
from app.etorniegpt.models import ChatMessage
from app.in_app_notifications.models import InAppNotification
from app.notifications.models import Notification
from app.organizations.models import OrganizationInvite, OrganizationMembership
from app.proposals.models import Proposal
from app.users.models import User

logger = logging.getLogger(__name__)


class ErasureBlocked(Exception):
    """Raised when active legal proceedings forbid erasure."""

    def __init__(self, blockers: list[Case]) -> None:
        self.blockers = blockers
        super().__init__(
            f"{len(blockers)} active case(s) block erasure"
        )


@dataclass
class ErasureSummary:
    user_id: uuid.UUID
    erased_at: datetime
    deleted_rows: dict[str, int] = field(default_factory=dict)
    deleted_files: int = 0
    retained_tables: list[str] = field(default_factory=list)
    anonymised: bool = False


async def _delete_count(db: AsyncSession, stmt) -> int:
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


def _remove_file(raw_path: str) -> bool:
    """Best-effort unlink of an on-disk file. Returns True if removed."""

    candidates = [Path(raw_path)]
    if not Path(raw_path).is_absolute():
        candidates.append(Path(settings.upload_dir) / raw_path)
    for candidate in candidates:
        try:
            if candidate.is_file():
                candidate.unlink()
                return True
        except OSError as exc:  # pragma: no cover - filesystem edge
            logger.warning("erasure: could not unlink %s: %s", candidate, exc)
    return False


async def erase_user(
    db: AsyncSession,
    user: User,
    *,
    reason: str,
) -> ErasureSummary:
    """Execute Article-17 erasure for ``user``.

    Raises :class:`ErasureBlocked` if an active proceeding forbids it.
    """

    if user.erased_at is not None:
        # Idempotent: already a tombstone.
        return ErasureSummary(
            user_id=user.id,
            erased_at=user.erased_at,
            anonymised=True,
        )

    blockers = await retention.find_erasure_blockers(db, user.id)
    if blockers:
        raise ErasureBlocked(blockers)

    uid = user.id
    summary = ErasureSummary(
        user_id=uid, erased_at=datetime.now(timezone.utc)
    )

    # --- delete on-disk files before their rows -------------------------
    upload_paths = (
        await db.execute(
            select(AgentUpload.stored_path).where(AgentUpload.user_id == uid)
        )
    ).scalars().all()
    for path in upload_paths:
        if path and _remove_file(path):
            summary.deleted_files += 1
    if user.avatar_path and _remove_file(user.avatar_path):
        summary.deleted_files += 1

    # --- DELETE tables (pure PII, no retention basis) -------------------
    # agent_messages reached via the subject's sessions; the session
    # shells stay so the draft → payment chain is never cascade-deleted.
    user_session_ids = select(AgentSession.id).where(
        AgentSession.user_id == uid
    )
    summary.deleted_rows["agent_messages"] = await _delete_count(
        db,
        delete(AgentMessage).where(
            AgentMessage.session_id.in_(user_session_ids)
        ),
    )
    summary.deleted_rows["agent_uploads"] = await _delete_count(
        db, delete(AgentUpload).where(AgentUpload.user_id == uid)
    )
    summary.deleted_rows["etorniegpt_chat_messages"] = await _delete_count(
        db, delete(ChatMessage).where(ChatMessage.user_id == uid)
    )
    summary.deleted_rows["case_notes"] = await _delete_count(
        db, delete(CaseNote).where(CaseNote.author_id == uid)
    )
    summary.deleted_rows["in_app_notifications"] = await _delete_count(
        db,
        delete(InAppNotification).where(
            InAppNotification.recipient_id == uid
        ),
    )
    summary.deleted_rows["notifications"] = await _delete_count(
        db, delete(Notification).where(Notification.created_by == uid)
    )
    summary.deleted_rows["proposals"] = await _delete_count(
        db, delete(Proposal).where(Proposal.created_by == uid)
    )
    summary.deleted_rows["braid_feedback_events"] = await _delete_count(
        db,
        delete(BraidCalibrationEvent).where(
            BraidCalibrationEvent.feedback_user_id == uid
        ),
    )
    summary.deleted_rows["organization_memberships"] = await _delete_count(
        db,
        delete(OrganizationMembership).where(
            OrganizationMembership.user_id == uid
        ),
    )

    # --- RETAIN with subject FKs nulled (invite history) ----------------
    await db.execute(
        update(OrganizationInvite)
        .where(OrganizationInvite.invited_by_user_id == uid)
        .values(invited_by_user_id=None)
    )
    await db.execute(
        update(OrganizationInvite)
        .where(OrganizationInvite.accepted_by_user_id == uid)
        .values(accepted_by_user_id=None)
    )

    # --- ANONYMISE the subject row (tombstone) --------------------------
    for column, value in retention.user_tombstone(uid).items():
        setattr(user, column, value)
    # Locked, unknowable password so the row stays authenticatable by the
    # CHECK constraint yet can never be used to sign in.
    user.hashed_password = hash_password(secrets.token_urlsafe(32))
    user.erased_at = summary.erased_at
    user.erasure_reason = reason
    summary.anonymised = True

    summary.retained_tables = [
        p.name
        for p in retention.policies_by_disposition(retention.Disposition.retain)
    ]

    await db.flush()
    logger.info(
        "GDPR erasure complete for user %s: deleted=%s files=%d",
        uid,
        summary.deleted_rows,
        summary.deleted_files,
    )
    return summary

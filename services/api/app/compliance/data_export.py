"""GDPR Article 20 data-portability export.

Collects every row of personal data tied to a single user across all
domain tables and returns one JSON-serialisable dict. The whole module
is a pure read path: it issues only ``SELECT``s on the caller's session
and never mutates anything.

Rows are serialised by introspecting each model's mapped columns rather
than by hand-listing fields, so the export tracks the schema as it
evolves. Two classes of column are always withheld:

* credential columns (``hashed_password``) — never portability data and
  a security risk to hand back, and
* deferred / large-binary columns (e.g. ``users.avatar_data``) — left
  unloaded so the serialiser never triggers a lazy IO inside the async
  session, and excluded because raw blobs are not Article-20 data.

The set of tables and the column each is linked to the subject through
is declared explicitly below; that mapping is schema knowledge, not a
hardcoded value, and is the one place to extend when a new
user-scoped table is added.
"""
from __future__ import annotations

import base64
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.agent.models import (
    AgentMessage,
    AgentSession,
    AgentUpload,
    CaseDraft,
    FilingAttempt,
    PaymentIntent,
)
from app.audit.models import AuditLog
from app.braid.models import BraidCalibrationEvent
from app.cases.models import Case, CaseEvent, CaseNote
from app.documents.models import Document
from app.etorniegpt.models import ChatMessage
from app.in_app_notifications.models import InAppNotification
from app.notifications.models import Notification
from app.organizations.models import OrganizationInvite, OrganizationMembership
from app.proposals.models import Proposal
from app.users.models import User

EXPORT_FORMAT = "etornie-gdpr-data-export"
EXPORT_VERSION = "1"
GDPR_BASIS = (
    "Regulation (EU) 2016/679 (GDPR) Article 20 — right to data portability"
)

# Column names never exported regardless of which table they live on:
# credentials and other secrets that are not portability data.
_SENSITIVE_COLUMNS = frozenset({"hashed_password"})


def _to_jsonable(value: Any) -> Any:
    """Convert a single column value into a JSON-serialisable form."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    return str(value)


def _serialize(row: Any) -> dict[str, Any]:
    """Serialise one ORM row using only its already-loaded columns.

    Deferred columns stay unloaded (so no lazy IO fires inside the async
    session) and known credential columns are dropped outright.
    """
    state = sa_inspect(row)
    unloaded = state.unloaded
    out: dict[str, Any] = {}
    for attr in state.mapper.column_attrs:
        key = attr.key
        if key in _SENSITIVE_COLUMNS or key in unloaded:
            continue
        out[key] = _to_jsonable(getattr(row, key))
    return out


async def _rows(db: AsyncSession, stmt) -> list[Any]:
    return list((await db.execute(stmt)).scalars().all())


async def _serialized_rows(db: AsyncSession, stmt) -> list[dict[str, Any]]:
    return [_serialize(row) for row in await _rows(db, stmt)]


def _in(column: ColumnElement, ids: list[uuid.UUID]):
    """``column IN ids`` with an explicit empty guard.

    SQLAlchemy emits a warning (and some backends choke) on an empty
    ``IN ()``; callers skip the query entirely when ``ids`` is empty, so
    this is only ever called with a non-empty list.
    """
    return column.in_(ids)


async def build_user_export(db: AsyncSession, user: User) -> dict[str, Any]:
    """Assemble the full personal-data export for ``user``.

    Returns a dict ready to be ``json.dumps``-ed. Every collection is a
    list of row dicts; empty lists are kept so the shape is stable and a
    consumer can tell "no rows" from "table not exported".
    """
    uid = user.id

    # --- tables linked directly to the subject ---------------------------
    memberships = await _serialized_rows(
        db,
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == uid
        ),
    )
    invites = await _serialized_rows(
        db,
        select(OrganizationInvite).where(
            (OrganizationInvite.invited_by_user_id == uid)
            | (OrganizationInvite.accepted_by_user_id == uid)
        ),
    )
    chat_messages = await _serialized_rows(
        db, select(ChatMessage).where(ChatMessage.user_id == uid)
    )
    case_notes = await _serialized_rows(
        db, select(CaseNote).where(CaseNote.author_id == uid)
    )
    documents = await _serialized_rows(
        db, select(Document).where(Document.uploaded_by == uid)
    )
    in_app_notifications = await _serialized_rows(
        db,
        select(InAppNotification).where(
            InAppNotification.recipient_id == uid
        ),
    )
    audit_logs = await _serialized_rows(
        db, select(AuditLog).where(AuditLog.actor_id == uid)
    )
    notifications = await _serialized_rows(
        db, select(Notification).where(Notification.created_by == uid)
    )
    proposals = await _serialized_rows(
        db, select(Proposal).where(Proposal.created_by == uid)
    )
    braid_feedback = await _serialized_rows(
        db,
        select(BraidCalibrationEvent).where(
            BraidCalibrationEvent.feedback_user_id == uid
        ),
    )
    agent_uploads = await _serialized_rows(
        db, select(AgentUpload).where(AgentUpload.user_id == uid)
    )

    # Parents fetched as ORM rows so we can both serialise them and read
    # their ids for the child queries below.
    cases = await _rows(db, select(Case).where(Case.client_id == uid))
    sessions = await _rows(
        db, select(AgentSession).where(AgentSession.user_id == uid)
    )
    drafts = await _rows(db, select(CaseDraft).where(CaseDraft.user_id == uid))

    case_ids = [c.id for c in cases]
    session_ids = [s.id for s in sessions]
    draft_ids = [d.id for d in drafts]

    # --- child tables reached through a parent the subject owns ----------
    agent_messages = (
        await _serialized_rows(
            db,
            select(AgentMessage).where(
                _in(AgentMessage.session_id, session_ids)
            ),
        )
        if session_ids
        else []
    )
    filing_attempts = (
        await _serialized_rows(
            db,
            select(FilingAttempt).where(
                _in(FilingAttempt.case_draft_id, draft_ids)
            ),
        )
        if draft_ids
        else []
    )
    payment_intents = (
        await _serialized_rows(
            db,
            select(PaymentIntent).where(
                _in(PaymentIntent.case_draft_id, draft_ids)
            ),
        )
        if draft_ids
        else []
    )
    case_events = (
        await _serialized_rows(
            db, select(CaseEvent).where(_in(CaseEvent.case_id, case_ids))
        )
        if case_ids
        else []
    )

    return {
        "export_format": EXPORT_FORMAT,
        "export_version": EXPORT_VERSION,
        "gdpr_basis": GDPR_BASIS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subject": {
            "user_id": str(uid),
            "email": user.email,
            "full_name": user.full_name,
            "wallet_address": user.wallet_address,
            "public_handle": user.public_handle,
        },
        "data": {
            "profile": _serialize(user),
            "organization_memberships": memberships,
            "organization_invites": invites,
            "cases": [_serialize(c) for c in cases],
            "case_events": case_events,
            "case_notes": case_notes,
            "documents": documents,
            "agent_sessions": [_serialize(s) for s in sessions],
            "agent_messages": agent_messages,
            "case_drafts": [_serialize(d) for d in drafts],
            "filing_attempts": filing_attempts,
            "payment_intents": payment_intents,
            "agent_uploads": agent_uploads,
            "etorniegpt_chat_messages": chat_messages,
            "in_app_notifications": in_app_notifications,
            "notifications": notifications,
            "proposals": proposals,
            "audit_logs": audit_logs,
            "braid_feedback_events": braid_feedback,
        },
    }

"""Service-level tests for the audit log (issue #30 review).

The trigger test (test_audit_append_only.py) proves the table is
append-only. These prove the other half: that the service layer writes
exactly one row per mutation, with the right actor and target, that
non-user actors are recorded, that a failing audit write does not undo the
business change, and that the GDPR export returns the rows.

Everything runs against the suite's SQLite DB through the real services.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLog
from app.audit.service import Actor, ActorType, log_audit_event
from app.cases.models import Case, CaseStatus
from app.cases.service import create_case, update_case
from app.compliance.data_export import build_user_export
from app.documents.service import create_document
from app.notifications.models import (
    Notification,
    NotificationStatus,
    NotificationType,
)
from app.notifications.service import cancel_notification, mark_sent
from app.users.models import User

pytestmark = pytest.mark.integration


async def _rows_for(db: AsyncSession, target_id: uuid.UUID) -> list[AuditLog]:
    result = await db.execute(
        select(AuditLog).where(AuditLog.target_id == target_id)
    )
    return list(result.scalars().all())


async def _make_notification(db: AsyncSession, created_by: uuid.UUID) -> Notification:
    notification = Notification(
        recipient_phone="+905551234567",
        message_type=NotificationType.text,
        message_body="hello",
        scheduled_at=datetime.now(timezone.utc),
        created_by=created_by,
    )
    db.add(notification)
    await db.flush()
    await db.refresh(notification)
    return notification


# ---------------------------------------------------------------------------
# One mutation -> exactly one row, with the right actor and target
# ---------------------------------------------------------------------------


async def test_case_create_writes_one_audit_row(
    db_session: AsyncSession, client_user: User
) -> None:
    case = await create_case(
        db_session,
        actor=Actor.user(client_user.id),
        title="Audited case",
        description="d",
        case_type="trademark",
        client_id=client_user.id,
        jurisdiction="Switzerland",
    )

    rows = await _rows_for(db_session, case.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == AuditAction.case_created
    assert row.actor_id == client_user.id
    assert row.actor_type == "user"
    assert row.target_type == "case"
    assert row.case_id == case.id


async def test_case_status_change_is_audited_as_a_status_change(
    db_session: AsyncSession, case_fixture: Case, admin_user: User
) -> None:
    # The fixture's own case_created row already exists; only the rows
    # written by the update itself are asserted on.
    before = {r.id for r in await _rows_for(db_session, case_fixture.id)}

    await update_case(
        db_session,
        case_fixture,
        actor=Actor.user(admin_user.id),
        status=CaseStatus.in_progress,
    )

    rows = [
        r
        for r in await _rows_for(db_session, case_fixture.id)
        if r.id not in before
    ]
    assert len(rows) == 1
    assert rows[0].action == AuditAction.case_status_changed
    assert rows[0].actor_id == admin_user.id
    assert rows[0].case_id == case_fixture.id
    assert "in_progress" in (rows[0].details or "")


async def test_case_field_update_is_audited_as_an_update(
    db_session: AsyncSession, case_fixture: Case, admin_user: User
) -> None:
    before = {r.id for r in await _rows_for(db_session, case_fixture.id)}

    await update_case(
        db_session,
        case_fixture,
        actor=Actor.user(admin_user.id),
        title="Renamed",
    )

    rows = [
        r
        for r in await _rows_for(db_session, case_fixture.id)
        if r.id not in before
    ]
    assert len(rows) == 1
    assert rows[0].action == AuditAction.case_updated


async def test_document_create_writes_one_audit_row(
    db_session: AsyncSession, case_fixture: Case, client_user: User
) -> None:
    document = await create_document(
        db_session,
        case_id=case_fixture.id,
        uploaded_by=client_user.id,
        filename="deed.pdf",
        file_path="/tmp/deed.pdf",
        file_type="application/pdf",
        file_size=10,
    )

    rows = await _rows_for(db_session, document.id)
    assert len(rows) == 1
    assert rows[0].action == AuditAction.document_created
    assert rows[0].actor_id == client_user.id
    assert rows[0].target_type == "document"
    assert rows[0].case_id == case_fixture.id


async def test_notification_send_is_audited_as_the_system_actor(
    db_session: AsyncSession, admin_user: User
) -> None:
    notification = await _make_notification(db_session, admin_user.id)

    await mark_sent(
        db_session,
        notification,
        whatsapp_message_id="wamid.1",
        actor=Actor.system(on_behalf_of=admin_user.id),
    )

    rows = await _rows_for(db_session, notification.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == AuditAction.notification_sent
    assert row.actor_type == "system"
    assert row.actor_id == admin_user.id
    # The recipient's number must never be copied into the audit trail.
    assert "905551234567" not in (row.details or "")


async def test_notification_cancel_is_audited(
    db_session: AsyncSession, admin_user: User
) -> None:
    notification = await _make_notification(db_session, admin_user.id)

    await cancel_notification(
        db_session, notification, actor=Actor.user(admin_user.id)
    )

    assert notification.status == NotificationStatus.cancelled
    rows = await _rows_for(db_session, notification.id)
    assert len(rows) == 1
    assert rows[0].action == AuditAction.notification_cancelled
    assert rows[0].actor_id == admin_user.id


# ---------------------------------------------------------------------------
# Actors without a user
# ---------------------------------------------------------------------------


async def test_system_actor_is_recorded_without_a_user(
    db_session: AsyncSession,
) -> None:
    target_id = uuid.uuid4()

    row = await log_audit_event(
        db_session,
        actor=Actor.system(),
        action=AuditAction.case_created,
        target_type="case",
        target_id=target_id,
    )

    assert row is not None
    assert row.actor_id is None
    assert row.actor_type == "system"
    assert len(await _rows_for(db_session, target_id)) == 1


def test_a_user_actor_requires_an_id() -> None:
    with pytest.raises(ValueError):
        Actor(ActorType.user, None)


async def test_log_audit_event_requires_an_actor(
    db_session: AsyncSession,
) -> None:
    # ``actor`` is a required keyword-only argument: forgetting it is a
    # programming error that fails loudly instead of skipping the audit.
    with pytest.raises(TypeError):
        await log_audit_event(  # type: ignore[call-arg]
            db_session,
            action=AuditAction.case_created,
            target_type="case",
            target_id=uuid.uuid4(),
        )


# ---------------------------------------------------------------------------
# A failing audit write must not undo or mask the business change
# ---------------------------------------------------------------------------


async def test_failing_audit_write_keeps_the_business_change(
    db_session: AsyncSession,
    case_fixture: Case,
    admin_user: User,
    monkeypatch,
    caplog,
) -> None:
    before = {r.id for r in await _rows_for(db_session, case_fixture.id)}
    original_flush = db_session.flush

    async def flush_that_fails_for_audit_rows(*args, **kwargs):
        if any(isinstance(obj, AuditLog) for obj in db_session.new):
            raise RuntimeError("audit insert failed")
        return await original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", flush_that_fails_for_audit_rows)

    with caplog.at_level(logging.WARNING, logger="app.audit.service"):
        updated = await update_case(
            db_session,
            case_fixture,
            actor=Actor.user(admin_user.id),
            title="Changed despite audit failure",
        )

    # The business mutation went through...
    assert updated.title == "Changed despite audit failure"
    stored = await db_session.execute(
        select(Case.title).where(Case.id == case_fixture.id)
    )
    assert stored.scalar_one() == "Changed despite audit failure"
    # ...the failure was logged rather than raised...
    assert "audit log write failed" in caplog.text
    # ...and no half-written audit row is left behind.
    after = {r.id for r in await _rows_for(db_session, case_fixture.id)}
    assert after == before


# ---------------------------------------------------------------------------
# GDPR export still returns the subject's audit rows
# ---------------------------------------------------------------------------


async def test_gdpr_export_returns_the_subjects_audit_rows(
    db_session: AsyncSession, client_user: User, admin_user: User
) -> None:
    case = await create_case(
        db_session,
        actor=Actor.user(client_user.id),
        title="Exported case",
        description="d",
        case_type="trademark",
        client_id=client_user.id,
        jurisdiction="Switzerland",
    )
    # Someone else's action must not show up in the subject's export.
    await log_audit_event(
        db_session,
        actor=Actor.user(admin_user.id),
        action=AuditAction.case_updated,
        target_type="case",
        target_id=case.id,
        case_id=case.id,
    )
    # Nor must a system row that has no user at all.
    await log_audit_event(
        db_session,
        actor=Actor.system(),
        action=AuditAction.case_updated,
        target_type="case",
        target_id=case.id,
        case_id=case.id,
    )

    export = await build_user_export(db_session, client_user)

    exported = export["data"]["audit_logs"]
    assert len(exported) == 1
    assert exported[0]["action"] == "case_created"
    assert exported[0]["actor_type"] == "user"
    assert exported[0]["actor_id"] == str(client_user.id)
    assert exported[0]["target_id"] == str(case.id)

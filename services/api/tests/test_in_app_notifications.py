"""Tests for in-app notification system."""

import io

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.in_app_notifications.models import InAppNotification, InAppNotificationType
from app.in_app_notifications.service import (
    create_notification,
    get_unread_count,
    list_notifications,
    mark_all_as_read,
    mark_as_read,
)
from app.users.models import User
from tests.conftest import auth_headers


# --- Service layer tests ---


@pytest.mark.asyncio
async def test_create_notification(db_session: AsyncSession, client_user: User, lawyer_user: User):
    notif = await create_notification(
        db_session,
        recipient_id=client_user.id,
        sender_id=lawyer_user.id,
        notification_type=InAppNotificationType.document_approved,
        title="Test",
        message="Test message",
    )
    assert notif.recipient_id == client_user.id
    assert notif.is_read is False


@pytest.mark.asyncio
async def test_list_notifications(db_session: AsyncSession, client_user: User):
    for i in range(3):
        await create_notification(
            db_session,
            recipient_id=client_user.id,
            notification_type=InAppNotificationType.note_added,
            title=f"Notif {i}",
            message=f"Message {i}",
        )
    notifs, total, unread = await list_notifications(db_session, client_user.id)
    assert total == 3
    assert unread == 3
    assert len(notifs) == 3


@pytest.mark.asyncio
async def test_mark_as_read(db_session: AsyncSession, client_user: User):
    notif = await create_notification(
        db_session,
        recipient_id=client_user.id,
        notification_type=InAppNotificationType.note_added,
        title="Test",
        message="Msg",
    )
    assert await get_unread_count(db_session, client_user.id) == 1
    await mark_as_read(db_session, notif.id, client_user.id)
    assert await get_unread_count(db_session, client_user.id) == 0


@pytest.mark.asyncio
async def test_mark_all_as_read(db_session: AsyncSession, client_user: User):
    for i in range(5):
        await create_notification(
            db_session,
            recipient_id=client_user.id,
            notification_type=InAppNotificationType.note_added,
            title=f"N{i}",
            message=f"M{i}",
        )
    count = await mark_all_as_read(db_session, client_user.id)
    assert count == 5
    assert await get_unread_count(db_session, client_user.id) == 0


# --- API endpoint tests ---


@pytest.mark.asyncio
async def test_list_endpoint(client: AsyncClient, db_session: AsyncSession, client_user: User):
    await create_notification(
        db_session,
        recipient_id=client_user.id,
        notification_type=InAppNotificationType.document_uploaded,
        title="API Test",
        message="API message",
    )
    resp = await client.get(
        "/in-app-notifications",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["unread_count"] == 1
    assert data["notifications"][0]["title"] == "API Test"


@pytest.mark.asyncio
async def test_unread_count_endpoint(client: AsyncClient, db_session: AsyncSession, lawyer_user: User):
    for _ in range(3):
        await create_notification(
            db_session,
            recipient_id=lawyer_user.id,
            notification_type=InAppNotificationType.document_uploaded,
            title="T",
            message="M",
        )
    resp = await client.get(
        "/in-app-notifications/unread-count",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 3


@pytest.mark.asyncio
async def test_mark_read_endpoint(client: AsyncClient, db_session: AsyncSession, client_user: User):
    notif = await create_notification(
        db_session,
        recipient_id=client_user.id,
        notification_type=InAppNotificationType.note_added,
        title="T",
        message="M",
    )
    resp = await client.patch(
        f"/in-app-notifications/{notif.id}/read",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_mark_all_read_endpoint(client: AsyncClient, db_session: AsyncSession, lawyer_user: User):
    for _ in range(4):
        await create_notification(
            db_session,
            recipient_id=lawyer_user.id,
            notification_type=InAppNotificationType.document_uploaded,
            title="T",
            message="M",
        )
    resp = await client.patch(
        "/in-app-notifications/read-all",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 200
    assert resp.json()["marked_read"] == 4


# --- Integration: triggers create notifications ---


@pytest.mark.asyncio
async def test_upload_triggers_notification(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
    lawyer_user: User,
    db_session: AsyncSession,
):
    """When client uploads a doc, lawyer gets a notification."""
    file = io.BytesIO(b"content")
    await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("test.pdf", file, "application/pdf")},
        headers=auth_headers(client_user),
    )

    # Lawyer should have received a notification
    resp = await client.get(
        "/in-app-notifications/unread-count",
        headers=auth_headers(lawyer_user),
    )
    assert resp.json()["unread_count"] >= 1


@pytest.mark.asyncio
async def test_note_triggers_notification(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
    lawyer_user: User,
):
    """When client adds a note, lawyer gets a notification."""
    await client.post(
        f"/cases/{case_fixture.id}/notes",
        json={"content": "Test note"},
        headers=auth_headers(client_user),
    )

    resp = await client.get(
        "/in-app-notifications/unread-count",
        headers=auth_headers(lawyer_user),
    )
    assert resp.json()["unread_count"] >= 1


@pytest.mark.asyncio
async def test_review_triggers_notification(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
    lawyer_user: User,
):
    """When lawyer approves a doc, client gets a notification."""
    # Upload as client
    file = io.BytesIO(b"data")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("doc.pdf", file, "application/pdf")},
        headers=auth_headers(client_user),
    )
    doc_id = upload_resp.json()["id"]

    # Approve as lawyer
    await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "approve"},
        headers=auth_headers(lawyer_user),
    )

    # Client should have notification
    resp = await client.get(
        "/in-app-notifications/unread-count",
        headers=auth_headers(client_user),
    )
    assert resp.json()["unread_count"] >= 1

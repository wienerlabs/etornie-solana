from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.notifications.models import Notification, NotificationStatus, NotificationType
from app.notifications.service import create_notification
from app.notifications.whatsapp import WhatsAppClient, get_whatsapp_client
from app.users.models import User
from tests.conftest import auth_headers


def _whatsapp_success_response() -> httpx.Response:
    """Build a mock WhatsApp API success response."""
    return httpx.Response(
        status_code=200,
        json={
            "messaging_product": "whatsapp",
            "contacts": [{"input": "905528144977", "wa_id": "905528144977"}],
            "messages": [{"id": "wamid.HBgNOTA1NTI4MTQ0OTc3FQIAERgS"}],
        },
        request=httpx.Request("POST", "https://graph.facebook.com/v22.0/123456/messages"),
    )


def _whatsapp_error_response() -> httpx.Response:
    """Build a mock WhatsApp API error response."""
    return httpx.Response(
        status_code=400,
        json={
            "error": {
                "message": "Invalid parameter",
                "type": "OAuthException",
                "code": 100,
            }
        },
        request=httpx.Request("POST", "https://graph.facebook.com/v22.0/123456/messages"),
    )


def _whatsapp_templates_response() -> httpx.Response:
    """Build a mock WhatsApp templates list response."""
    return httpx.Response(
        status_code=200,
        json={
            "data": [
                {
                    "name": "hello_world",
                    "language": "en_US",
                    "status": "APPROVED",
                    "category": "UTILITY",
                },
                {
                    "name": "appointment_reminder",
                    "language": "en_US",
                    "status": "APPROVED",
                    "category": "UTILITY",
                },
            ]
        },
        request=httpx.Request(
            "GET",
            "https://graph.facebook.com/v22.0/789012/message_templates",
        ),
    )


def _future_dt(minutes: int = 60) -> str:
    """Return an ISO datetime string `minutes` in the future."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past_dt(minutes: int = 5) -> str:
    """Return an ISO datetime string `minutes` in the past."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _make_mock_whatsapp_client(
    post_return: httpx.Response | None = None,
    post_side_effect: Exception | None = None,
    get_return: httpx.Response | None = None,
) -> WhatsAppClient:
    """Create a real WhatsAppClient with its _http methods mocked."""
    wa_client = WhatsAppClient(
        api_token="test-token",
        phone_number_id="123456",
        api_version="v22.0",
    )
    mock_http = AsyncMock()

    if post_side_effect is not None:
        mock_http.post.side_effect = post_side_effect
    elif post_return is not None:
        mock_http.post.return_value = post_return

    if get_return is not None:
        mock_http.get.return_value = get_return

    wa_client._http = mock_http
    return wa_client


class TestCreateNotification:
    """Tests for POST /notifications."""

    async def test_create_template_notification(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.post(
            "/notifications",
            headers=headers,
            json={
                "recipient_phone": "905528144977",
                "recipient_name": "Test User",
                "message_type": "template",
                "template_name": "hello_world",
                "template_language": "en_US",
                "scheduled_at": _future_dt(),
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["recipient_phone"] == "905528144977"
        assert data["message_type"] == "template"
        assert data["template_name"] == "hello_world"
        assert data["status"] == "pending"
        assert data["created_by"] == str(admin_user.id)

    async def test_create_text_notification(
        self,
        client: AsyncClient,
        lawyer_user: User,
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.post(
            "/notifications",
            headers=headers,
            json={
                "recipient_phone": "+905528144977",
                "message_type": "text",
                "message_body": "Your appointment is tomorrow at 10am.",
                "scheduled_at": _future_dt(),
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["message_type"] == "text"
        assert data["message_body"] == "Your appointment is tomorrow at 10am."
        # Phone should have + stripped
        assert data["recipient_phone"] == "905528144977"

    async def test_create_template_without_name_fails(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.post(
            "/notifications",
            headers=headers,
            json={
                "recipient_phone": "905528144977",
                "message_type": "template",
                "scheduled_at": _future_dt(),
            },
        )
        assert response.status_code == 422

    async def test_create_text_without_body_fails(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.post(
            "/notifications",
            headers=headers,
            json={
                "recipient_phone": "905528144977",
                "message_type": "text",
                "scheduled_at": _future_dt(),
            },
        )
        assert response.status_code == 422

    async def test_client_cannot_create_notification(
        self,
        client: AsyncClient,
        client_user: User,
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.post(
            "/notifications",
            headers=headers,
            json={
                "recipient_phone": "905528144977",
                "message_type": "template",
                "template_name": "hello_world",
                "scheduled_at": _future_dt(),
            },
        )
        assert response.status_code == 403


class TestListNotifications:
    """Tests for GET /notifications."""

    async def test_admin_sees_all_notifications(
        self,
        client: AsyncClient,
        admin_user: User,
        lawyer_user: User,
        db_session: AsyncSession,
    ) -> None:
        # Create notifications from different users
        await create_notification(
            db_session,
            created_by=admin_user.id,
            recipient_phone="905528144977",
            message_type=NotificationType.template,
            template_name="hello_world",
            template_language="en_US",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await create_notification(
            db_session,
            created_by=lawyer_user.id,
            recipient_phone="905528144978",
            message_type=NotificationType.text,
            message_body="Reminder",
            template_language="en_US",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )

        headers = auth_headers(admin_user)
        response = await client.get("/notifications", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["notifications"]) == 2

    async def test_client_cannot_list_notifications(
        self,
        client: AsyncClient,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        # Listing notifications is admin-only in the two-tier model; the
        # old lawyer "sees only own" tier was retired on 2026-05-02.
        await create_notification(
            db_session,
            created_by=client_user.id,
            recipient_phone="905528144977",
            message_type=NotificationType.template,
            template_name="hello_world",
            template_language="en_US",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        headers = auth_headers(client_user)
        response = await client.get("/notifications", headers=headers)
        assert response.status_code == 403


class TestGetNotification:
    """Tests for GET /notifications/{id}."""

    async def test_get_notification_detail(
        self,
        client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        notification = await create_notification(
            db_session,
            created_by=admin_user.id,
            recipient_phone="905528144977",
            recipient_name="Test User",
            message_type=NotificationType.template,
            template_name="hello_world",
            template_language="en_US",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        headers = auth_headers(admin_user)
        response = await client.get(
            f"/notifications/{notification.id}", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(notification.id)
        assert data["recipient_phone"] == "905528144977"
        assert data["recipient_name"] == "Test User"


class TestCancelNotification:
    """Tests for DELETE /notifications/{id}."""

    async def test_cancel_pending_notification(
        self,
        client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        notification = await create_notification(
            db_session,
            created_by=admin_user.id,
            recipient_phone="905528144977",
            message_type=NotificationType.template,
            template_name="hello_world",
            template_language="en_US",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        headers = auth_headers(admin_user)
        response = await client.delete(
            f"/notifications/{notification.id}", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"


class TestSendNow:
    """Tests for POST /notifications/send."""

    async def test_send_immediate_message_success(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        wa_client = _make_mock_whatsapp_client(
            post_return=_whatsapp_success_response(),
        )
        app.dependency_overrides[get_whatsapp_client] = lambda: wa_client

        try:
            headers = auth_headers(admin_user)
            response = await client.post(
                "/notifications/send",
                headers=headers,
                json={
                    "recipient_phone": "905528144977",
                    "message_type": "template",
                    "template_name": "hello_world",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["whatsapp_message_id"] == "wamid.HBgNOTA1NTI4MTQ0OTc3FQIAERgS"
            wa_client._http.post.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_whatsapp_client, None)

    async def test_send_immediate_message_api_error(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        wa_client = _make_mock_whatsapp_client(
            post_return=_whatsapp_error_response(),
        )
        app.dependency_overrides[get_whatsapp_client] = lambda: wa_client

        try:
            headers = auth_headers(admin_user)
            response = await client.post(
                "/notifications/send",
                headers=headers,
                json={
                    "recipient_phone": "905528144977",
                    "message_type": "text",
                    "message_body": "Test message",
                },
            )
            # The WhatsApp client raises HTTPException with 400 for client errors
            assert response.status_code == 400
            assert "WhatsApp API error" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_whatsapp_client, None)

    async def test_send_requires_auth(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.post(
            "/notifications/send",
            json={
                "recipient_phone": "905528144977",
                "message_type": "text",
                "message_body": "No auth",
            },
        )
        # Without Bearer token, the endpoint requires authentication
        assert response.status_code in (401, 403)


class TestProcessScheduler:
    """Tests for POST /notifications/process."""

    async def test_process_sends_due_notifications(
        self,
        client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        wa_client = _make_mock_whatsapp_client(
            post_return=_whatsapp_success_response(),
        )
        app.dependency_overrides[get_whatsapp_client] = lambda: wa_client

        try:
            # Create a notification scheduled in the past (due now)
            await create_notification(
                db_session,
                created_by=admin_user.id,
                recipient_phone="905528144977",
                message_type=NotificationType.template,
                template_name="hello_world",
                template_language="en_US",
                scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )

            headers = auth_headers(admin_user)
            response = await client.post("/notifications/process", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["processed"] == 1
            assert data["sent"] == 1
            assert data["failed"] == 0
            wa_client._http.post.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_whatsapp_client, None)

    async def test_process_retries_failed_notification(
        self,
        client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        wa_client = _make_mock_whatsapp_client(
            post_side_effect=Exception("Connection refused"),
        )
        app.dependency_overrides[get_whatsapp_client] = lambda: wa_client

        try:
            # Create a notification scheduled in the past with retries remaining
            await create_notification(
                db_session,
                created_by=admin_user.id,
                recipient_phone="905528144977",
                message_type=NotificationType.text,
                message_body="Retry test",
                template_language="en_US",
                scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                max_retries=3,
            )

            headers = auth_headers(admin_user)
            response = await client.post("/notifications/process", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["processed"] == 1
            # retry_count (0 + 1 = 1) < max_retries (3), so still pending
            assert data["sent"] == 0
            assert data["failed"] == 0
        finally:
            app.dependency_overrides.pop(get_whatsapp_client, None)

    async def test_process_marks_failed_after_max_retries(
        self,
        client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        wa_client = _make_mock_whatsapp_client(
            post_side_effect=Exception("Persistent failure"),
        )
        app.dependency_overrides[get_whatsapp_client] = lambda: wa_client

        try:
            # Create a notification that will exceed max retries on this attempt
            await create_notification(
                db_session,
                created_by=admin_user.id,
                recipient_phone="905528144977",
                message_type=NotificationType.text,
                message_body="Max retry test",
                template_language="en_US",
                scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                max_retries=1,
                retry_count=0,
            )

            headers = auth_headers(admin_user)
            response = await client.post("/notifications/process", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["processed"] == 1
            assert data["sent"] == 0
            # retry_count (0 + 1 = 1) >= max_retries (1), so failed
            assert data["failed"] == 1
        finally:
            app.dependency_overrides.pop(get_whatsapp_client, None)


class TestListTemplates:
    """Tests for GET /notifications/templates/list."""

    async def test_list_templates_success(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        wa_client = _make_mock_whatsapp_client(
            get_return=_whatsapp_templates_response(),
        )
        app.dependency_overrides[get_whatsapp_client] = lambda: wa_client

        try:
            headers = auth_headers(admin_user)
            response = await client.get("/notifications/templates/list", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["name"] == "hello_world"
            assert data[1]["name"] == "appointment_reminder"
            wa_client._http.get.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_whatsapp_client, None)

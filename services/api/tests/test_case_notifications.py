"""Tests for auto-notification service on case creation."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.notifications.case_notifications import (
    notify_case_created,
    send_case_created_email,
    send_case_created_whatsapp,
)
from app.notifications.models import Notification, NotificationType
from app.users.models import User


def _emailjs_success_response() -> httpx.Response:
    """Build a mock EmailJS success response."""
    return httpx.Response(
        status_code=200,
        text="OK",
        request=httpx.Request("POST", "https://api.emailjs.com/api/v1.0/email/send"),
    )


def _emailjs_error_response() -> httpx.Response:
    """Build a mock EmailJS error response."""
    return httpx.Response(
        status_code=400,
        text="Bad Request",
        request=httpx.Request("POST", "https://api.emailjs.com/api/v1.0/email/send"),
    )


class TestCaseCreatedEmail:
    """Tests for send_case_created_email."""

    async def test_case_created_sends_email(
        self,
        client_user: User,
        case_fixture: Case,
    ) -> None:
        """Email is sent with correct params when EmailJS is configured."""
        mock_response = _emailjs_success_response()
        mock_post = AsyncMock(return_value=mock_response)

        with (
            patch("app.notifications.case_notifications.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.emailjs_public_key = "test-key"
            mock_settings.emailjs_private_key = "test-private-key"
            mock_settings.emailjs_service_id = "test-service"
            mock_settings.emailjs_case_template_id = "test-case-template"

            mock_http_instance = AsyncMock()
            mock_http_instance.post = mock_post
            mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http_instance

            result = await send_case_created_email(client_user, case_fixture)

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["template_id"] == "test-case-template"
        assert payload["template_params"]["to_name"] == client_user.full_name
        assert payload["template_params"]["email"] == client_user.email
        assert payload["template_params"]["case_number"] == case_fixture.case_number
        assert payload["template_params"]["case_title"] == case_fixture.title

    async def test_case_created_email_skips_when_not_configured(
        self,
        client_user: User,
        case_fixture: Case,
    ) -> None:
        """No error when EmailJS case template is not configured."""
        with patch("app.notifications.case_notifications.settings") as mock_settings:
            mock_settings.emailjs_public_key = ""
            mock_settings.emailjs_case_template_id = ""

            result = await send_case_created_email(client_user, case_fixture)

        assert result is False

    async def test_case_created_email_skips_when_template_id_missing(
        self,
        client_user: User,
        case_fixture: Case,
    ) -> None:
        """No error when only case template ID is missing."""
        with patch("app.notifications.case_notifications.settings") as mock_settings:
            mock_settings.emailjs_public_key = "test-key"
            mock_settings.emailjs_case_template_id = ""

            result = await send_case_created_email(client_user, case_fixture)

        assert result is False

    async def test_case_created_email_returns_false_on_api_error(
        self,
        client_user: User,
        case_fixture: Case,
    ) -> None:
        """Returns False when EmailJS returns an error status."""
        mock_response = _emailjs_error_response()
        mock_post = AsyncMock(return_value=mock_response)

        with (
            patch("app.notifications.case_notifications.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.emailjs_public_key = "test-key"
            mock_settings.emailjs_private_key = "test-private-key"
            mock_settings.emailjs_service_id = "test-service"
            mock_settings.emailjs_case_template_id = "test-case-template"

            mock_http_instance = AsyncMock()
            mock_http_instance.post = mock_post
            mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http_instance

            result = await send_case_created_email(client_user, case_fixture)

        assert result is False


class TestCaseCreatedWhatsApp:
    """Tests for send_case_created_whatsapp."""

    async def test_case_created_creates_whatsapp_notification(
        self,
        db_session: AsyncSession,
        client_user: User,
        admin_user: User,
        case_fixture: Case,
    ) -> None:
        """A notification record is created in the DB for WhatsApp delivery."""
        result = await send_case_created_whatsapp(
            db_session, client_user, case_fixture, admin_user.id
        )

        assert result is True

        # Verify the notification was persisted
        query = select(Notification).where(Notification.case_id == case_fixture.id)
        db_result = await db_session.execute(query)
        notification = db_result.scalar_one_or_none()

        assert notification is not None
        assert notification.recipient_phone == client_user.phone
        assert notification.recipient_name == client_user.full_name
        assert notification.message_type == NotificationType.template
        assert notification.template_name == "new_case_opened"
        assert notification.template_language == "tr"
        assert notification.created_by == admin_user.id
        assert notification.case_id == case_fixture.id
        assert case_fixture.case_number in notification.message_body

    async def test_case_created_whatsapp_skips_no_phone(
        self,
        db_session: AsyncSession,
        admin_user: User,
        case_fixture: Case,
    ) -> None:
        """No notification created when client has no phone number."""
        from tests.conftest import _create_user_in_db

        # Create a client user without a phone number
        no_phone_user = await _create_user_in_db(
            db_session,
            email="nophone@etornie.ch",
            password="NoPhone123!",
            full_name="No Phone User",
            role=client_user_role_value(),
        )

        result = await send_case_created_whatsapp(
            db_session, no_phone_user, case_fixture, admin_user.id
        )

        assert result is False

        # Verify no notification was created
        query = select(Notification).where(Notification.case_id == case_fixture.id)
        db_result = await db_session.execute(query)
        notification = db_result.scalar_one_or_none()
        assert notification is None

    async def test_case_created_whatsapp_skips_when_not_configured(
        self,
        db_session: AsyncSession,
        client_user: User,
        admin_user: User,
        case_fixture: Case,
    ) -> None:
        """No notification when WhatsApp is not configured."""
        with patch("app.notifications.case_notifications.settings") as mock_settings:
            mock_settings.whatsapp_api_token = ""
            mock_settings.whatsapp_phone_number_id = ""

            result = await send_case_created_whatsapp(
                db_session, client_user, case_fixture, admin_user.id
            )

        assert result is False


class TestNotifyCaseCreated:
    """Tests for the combined notify_case_created function."""

    async def test_notify_case_created_returns_results(
        self,
        db_session: AsyncSession,
        client_user: User,
        admin_user: User,
        case_fixture: Case,
    ) -> None:
        """notify_case_created returns status for both channels."""
        mock_response = _emailjs_success_response()
        mock_post = AsyncMock(return_value=mock_response)

        with (
            patch("app.notifications.case_notifications.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.emailjs_public_key = "test-key"
            mock_settings.emailjs_private_key = "test-private-key"
            mock_settings.emailjs_service_id = "test-service"
            mock_settings.emailjs_case_template_id = "test-case-template"
            mock_settings.whatsapp_api_token = "test-token"
            mock_settings.whatsapp_phone_number_id = "123456"

            mock_http_instance = AsyncMock()
            mock_http_instance.post = mock_post
            mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http_instance

            result = await notify_case_created(
                db_session, case_fixture, client_user, admin_user.id
            )

        assert result["email_sent"] is True
        assert result["whatsapp_created"] is True


def client_user_role_value():
    """Return the UserRole.client enum value."""
    from app.users.models import UserRole
    return UserRole.client

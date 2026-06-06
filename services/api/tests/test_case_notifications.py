"""Tests for auto-notification service on case creation."""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.notifications.case_notifications import (
    notify_case_created,
    send_case_created_email,
    send_case_created_email_to_guest,
    send_case_created_whatsapp,
)
from app.notifications.models import Notification, NotificationType
from app.users.models import User


class TestCaseCreatedEmail:
    """Tests for send_case_created_email (SMTP transport)."""

    async def test_case_created_sends_email(
        self,
        client_user: User,
        case_fixture: Case,
    ) -> None:
        """Email goes out with the case details in subject + body."""
        with patch(
            "app.notifications.case_notifications.send_email",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            result = await send_case_created_email(client_user, case_fixture)

        assert result is True
        mock_send.assert_awaited_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["to_email"] == client_user.email
        assert kwargs["to_name"] == client_user.full_name
        assert case_fixture.case_number in kwargs["subject"]
        assert case_fixture.case_number in kwargs["body"]
        assert case_fixture.title in kwargs["body"]

    async def test_case_created_email_returns_false_when_transport_fails(
        self,
        client_user: User,
        case_fixture: Case,
    ) -> None:
        """A relay failure (transport returns False) propagates as False."""
        with patch(
            "app.notifications.case_notifications.send_email",
            new=AsyncMock(return_value=False),
        ) as mock_send:
            result = await send_case_created_email(client_user, case_fixture)

        assert result is False
        mock_send.assert_awaited_once()

    async def test_guest_email_skips_without_address(
        self,
        case_fixture: Case,
    ) -> None:
        """No recipient address → return False without touching the transport."""
        with patch(
            "app.notifications.case_notifications.send_email",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            result = await send_case_created_email_to_guest("", "Guest", case_fixture)

        assert result is False
        mock_send.assert_not_awaited()


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
        with (
            patch(
                "app.notifications.case_notifications.send_email",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.notifications.case_notifications._process_now",
                new=AsyncMock(),
            ),
            patch("app.notifications.case_notifications.settings") as mock_settings,
        ):
            mock_settings.whatsapp_api_token = "test-token"
            mock_settings.whatsapp_phone_number_id = "123456"

            result = await notify_case_created(
                db_session, case_fixture, client_user, admin_user.id
            )

        assert result["email_sent"] is True
        assert result["whatsapp_created"] is True


def client_user_role_value():
    """Return the UserRole.client enum value."""
    from app.users.models import UserRole
    return UserRole.client

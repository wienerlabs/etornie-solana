"""Tests for the server-side SMTP email transport + OTP email (#29).

Pure unit tests — ``aiosmtplib.send`` is mocked so nothing leaves the box.
They lock in the behaviour the rest of the email stack relies on:

- not configured  -> return False, never touch the relay;
- port 587        -> STARTTLS; port 465 -> implicit TLS (never both);
- relay error     -> swallowed, reported as False;
- the OTP body actually carries the code.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosmtplib
import pytest

from app.auth.email_verification import send_verification_email
from app.notifications import email_transport
from app.notifications.email_transport import is_configured, send_email


def _smtp_settings(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "",
        "smtp_starttls": True,
        "smtp_use_tls": False,
        "smtp_from_email": "no-reply@etornie.ch",
        "smtp_from_name": "Etornie",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.unit
class TestSmtpTransport:
    async def test_skips_when_not_configured(self) -> None:
        fake = _smtp_settings(smtp_host="", smtp_from_email="")
        with (
            patch.object(email_transport, "settings", fake),
            patch("aiosmtplib.send", new=AsyncMock()) as mock_send,
        ):
            sent = await send_email(
                to_email="a@example.com", to_name="A", subject="s", body="b"
            )
        assert sent is False
        mock_send.assert_not_awaited()

    async def test_sends_when_configured(self) -> None:
        with (
            patch.object(email_transport, "settings", _smtp_settings()),
            patch("aiosmtplib.send", new=AsyncMock()) as mock_send,
        ):
            sent = await send_email(
                to_email="client@example.com",
                to_name="Client",
                subject="Hello",
                body="Body text",
            )
        assert sent is True
        mock_send.assert_awaited_once()
        message = mock_send.call_args.args[0]
        assert message["To"] == "Client <client@example.com>"
        assert message["From"] == "Etornie <no-reply@etornie.ch>"
        assert message["Subject"] == "Hello"
        assert "Body text" in message.get_content()
        assert mock_send.call_args.kwargs["start_tls"] is True
        assert mock_send.call_args.kwargs["use_tls"] is False

    async def test_implicit_tls_disables_starttls(self) -> None:
        # Port 465 / implicit TLS must never also offer STARTTLS.
        fake = _smtp_settings(smtp_port=465, smtp_use_tls=True, smtp_starttls=True)
        with (
            patch.object(email_transport, "settings", fake),
            patch("aiosmtplib.send", new=AsyncMock()) as mock_send,
        ):
            await send_email(
                to_email="c@example.com", to_name=None, subject="s", body="b"
            )
        assert mock_send.call_args.kwargs["use_tls"] is True
        assert mock_send.call_args.kwargs["start_tls"] is False

    async def test_returns_false_on_smtp_error(self) -> None:
        with (
            patch.object(email_transport, "settings", _smtp_settings()),
            patch(
                "aiosmtplib.send",
                new=AsyncMock(side_effect=aiosmtplib.SMTPException("boom")),
            ),
        ):
            sent = await send_email(
                to_email="c@example.com", to_name=None, subject="s", body="b"
            )
        assert sent is False

    def test_is_configured(self) -> None:
        with patch.object(email_transport, "settings", _smtp_settings()):
            assert is_configured() is True
        with patch.object(email_transport, "settings", _smtp_settings(smtp_host="")):
            assert is_configured() is False


@pytest.mark.unit
class TestOtpEmail:
    async def test_otp_email_carries_code(self) -> None:
        with patch(
            "app.auth.email_verification.send_email",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            sent = await send_verification_email("user@example.com", "User", "123456")
        assert sent is True
        kwargs = mock_send.call_args.kwargs
        assert kwargs["to_email"] == "user@example.com"
        assert "123456" in kwargs["body"]
        assert "verification code" in kwargs["subject"].lower()

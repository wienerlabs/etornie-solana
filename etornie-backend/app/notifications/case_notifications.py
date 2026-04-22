"""Auto-notification service for case events."""

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.config import settings
from app.notifications.models import NotificationType
from app.notifications.scheduler import process_pending_notifications
from app.notifications.service import create_notification
from app.notifications.whatsapp import WhatsAppClient
from app.users.models import User

logger = logging.getLogger(__name__)


async def _process_now(db: AsyncSession) -> None:
    """Immediately process pending notifications to send WhatsApp messages."""
    if not settings.whatsapp_api_token or not settings.whatsapp_phone_number_id:
        return
    try:
        wa_client = WhatsAppClient(
            api_token=settings.whatsapp_api_token,
            phone_number_id=settings.whatsapp_phone_number_id,
            api_version=settings.whatsapp_api_version,
        )
        await process_pending_notifications(db, wa_client)
        await wa_client.close()
    except Exception as exc:
        logger.warning("Failed to process notifications immediately: %s", exc)


async def send_case_created_email(client_user: User, case: Case) -> bool:
    """Send email notification to client about new case via EmailJS."""
    if not settings.emailjs_public_key or not settings.emailjs_case_template_id:
        logger.warning("EmailJS case template not configured, skipping email")
        return False

    if not client_user.email:
        return False

    url = "https://api.emailjs.com/api/v1.0/email/send"
    payload = {
        "service_id": settings.emailjs_service_id,
        "template_id": settings.emailjs_case_template_id,
        "user_id": settings.emailjs_public_key,
        "accessToken": settings.emailjs_private_key,
        "template_params": {
            "to_name": client_user.full_name,
            "email": client_user.email,
            "case_number": case.case_number,
            "case_title": case.title,
            "case_type": case.case_type.value if hasattr(case.case_type, "value") else str(case.case_type),
            "deadline": str(case.deadline) if case.deadline else "Not set",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            response = await http_client.post(url, json=payload)
            if response.status_code == 200:
                logger.info("Case creation email sent to %s", client_user.email)
                return True
            else:
                logger.warning("EmailJS returned %s: %s", response.status_code, response.text)
                return False
    except Exception as exc:
        logger.warning("Failed to send case creation email: %s", exc)
        return False


async def send_case_created_whatsapp(
    db: AsyncSession,
    client_user: User,
    case: Case,
    created_by_id: object,
) -> bool:
    """Send WhatsApp notification to client about new case.

    Uses 'new_case_opened' template.
    """
    if not client_user.phone:
        logger.info("Client %s has no phone number, skipping WhatsApp", client_user.email)
        return False

    if not settings.whatsapp_api_token or not settings.whatsapp_phone_number_id:
        logger.warning("WhatsApp not configured, skipping")
        return False

    now = datetime.now(timezone.utc)

    wa_template_name = "new_case_opened"
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": client_user.full_name},
                {"type": "text", "text": case.case_number},
                {"type": "text", "text": case.title},
                {"type": "text", "text": str(case.deadline) if case.deadline else "Not set"},
            ],
        }
    ]

    try:
        await create_notification(
            db,
            created_by=created_by_id,
            recipient_phone=client_user.phone,
            recipient_name=client_user.full_name,
            message_type=NotificationType.template,
            template_name=wa_template_name,
            template_language="tr",
            template_components=json.dumps(components),
            message_body=f"New case {case.case_number} opened for {client_user.full_name}",
            scheduled_at=now,
            case_id=case.id,
        )
        logger.info("WhatsApp notification created for case %s", case.case_number)
        await _process_now(db)
        return True
    except Exception as exc:
        logger.warning("Failed to create WhatsApp notification: %s", exc)
        return False


async def send_case_created_email_to_guest(
    email: str, name: str, case: Case
) -> bool:
    """Send email notification to an unregistered (guest) client."""
    if not settings.emailjs_public_key or not settings.emailjs_case_template_id:
        logger.warning("EmailJS case template not configured, skipping email")
        return False

    url = "https://api.emailjs.com/api/v1.0/email/send"
    payload = {
        "service_id": settings.emailjs_service_id,
        "template_id": settings.emailjs_case_template_id,
        "user_id": settings.emailjs_public_key,
        "accessToken": settings.emailjs_private_key,
        "template_params": {
            "to_name": name,
            "email": email,
            "case_number": case.case_number,
            "case_title": case.title,
            "case_type": case.case_type.value if hasattr(case.case_type, "value") else str(case.case_type),
            "deadline": str(case.deadline) if case.deadline else "Not set",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            response = await http_client.post(url, json=payload)
            if response.status_code == 200:
                logger.info("Case creation email sent to guest %s", email)
                return True
            else:
                logger.warning("EmailJS returned %s: %s", response.status_code, response.text)
                return False
    except Exception as exc:
        logger.warning("Failed to send case creation email to guest: %s", exc)
        return False


async def send_case_created_whatsapp_to_guest(
    db: AsyncSession,
    phone: str,
    name: str,
    case: Case,
    created_by_id: object,
) -> bool:
    """Create WhatsApp notification for an unregistered (guest) client."""
    if not settings.whatsapp_api_token or not settings.whatsapp_phone_number_id:
        logger.warning("WhatsApp not configured, skipping")
        return False

    now = datetime.now(timezone.utc)

    wa_template_name = "new_case_opened"
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": name},
                {"type": "text", "text": case.case_number},
                {"type": "text", "text": case.title},
                {"type": "text", "text": str(case.deadline) if case.deadline else "Not set"},
            ],
        }
    ]

    try:
        await create_notification(
            db,
            created_by=created_by_id,
            recipient_phone=phone,
            recipient_name=name,
            message_type=NotificationType.template,
            template_name=wa_template_name,
            template_language="tr",
            template_components=json.dumps(components),
            message_body=f"New case {case.case_number} opened for {name}",
            scheduled_at=now,
            case_id=case.id,
        )
        logger.info("WhatsApp notification created for guest case %s", case.case_number)
        await _process_now(db)
        return True
    except Exception as exc:
        logger.warning("Failed to create WhatsApp notification for guest: %s", exc)
        return False


async def notify_case_created(
    db: AsyncSession,
    case: Case,
    client_user: User,
    created_by_id: object,
) -> dict:
    """Send all notifications for a new case.

    Returns: { email_sent: bool, whatsapp_created: bool }
    """
    email_sent = await send_case_created_email(client_user, case)
    whatsapp_created = await send_case_created_whatsapp(
        db, client_user, case, created_by_id
    )
    # Process pending notifications immediately so WhatsApp sends now
    if whatsapp_created:
        await _process_now(db)

    return {
        "email_sent": email_sent,
        "whatsapp_created": whatsapp_created,
    }

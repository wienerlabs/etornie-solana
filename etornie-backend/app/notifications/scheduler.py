import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import NotificationType
from app.notifications.service import get_pending_notifications, mark_failed, mark_sent
from app.notifications.whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)


async def process_pending_notifications(
    db: AsyncSession,
    whatsapp_client: WhatsAppClient,
) -> dict:
    """Process all pending notifications that are due.

    Returns: { processed: int, sent: int, failed: int }
    """
    now = datetime.now(timezone.utc)
    pending = await get_pending_notifications(db, before=now)

    result = {"processed": len(pending), "sent": 0, "failed": 0}

    for notification in pending:
        try:
            if notification.message_type == NotificationType.template:
                components = None
                if notification.template_components:
                    try:
                        components = json.loads(notification.template_components)
                    except json.JSONDecodeError:
                        pass
                response = await whatsapp_client.send_template_message(
                    to=notification.recipient_phone,
                    template_name=notification.template_name or "",
                    language_code=notification.template_language,
                    components=components,
                )
            else:
                response = await whatsapp_client.send_text_message(
                    to=notification.recipient_phone,
                    body=notification.message_body or "",
                )

            messages = response.get("messages", [])
            wa_message_id = messages[0]["id"] if messages else "unknown"
            await mark_sent(db, notification, whatsapp_message_id=wa_message_id)
            result["sent"] += 1

        except Exception as exc:
            error_msg = str(exc)
            logger.warning(
                "Failed to send notification %s: %s",
                notification.id,
                error_msg,
            )

            notification.retry_count += 1
            if notification.retry_count >= notification.max_retries:
                await mark_failed(db, notification, error_message=error_msg)
                result["failed"] += 1
            else:
                # Keep as pending for next retry — just update retry_count
                await db.flush()
                await db.refresh(notification)

    return result

import random
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

# In-memory store for pending verifications (use Redis in production)
_pending_verifications: dict[str, dict] = {}


def generate_code() -> str:
    """Generate a 6-digit verification code."""
    return str(random.randint(100000, 999999))


async def send_verification_email(to_email: str, to_name: str, code: str) -> bool:
    """Send verification code via EmailJS REST API."""
    if not settings.emailjs_public_key or not settings.emailjs_service_id:
        raise Exception("EmailJS not configured")

    expires_at = datetime.now() + timedelta(minutes=10)
    expires_str = expires_at.strftime("%H:%M")

    url = "https://api.emailjs.com/api/v1.0/email/send"
    payload = {
        "service_id": settings.emailjs_service_id,
        "template_id": settings.emailjs_template_id,
        "user_id": settings.emailjs_public_key,
        "accessToken": settings.emailjs_private_key,
        "template_params": {
            "passcode": code,
            "time": expires_str,
            "to_name": to_name,
            "email": to_email,
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)
        return response.status_code == 200


def store_pending(email: str, code: str, registration_data: dict) -> None:
    """Store pending verification with 10-minute expiry."""
    _pending_verifications[email] = {
        "code": code,
        "data": registration_data,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    }


def verify_code(email: str, code: str) -> dict | None:
    """Verify the code and return registration data if valid."""
    pending = _pending_verifications.get(email)
    if pending is None:
        return None
    if datetime.now(timezone.utc) > pending["expires_at"]:
        del _pending_verifications[email]
        return None
    if pending["code"] != code:
        return None
    data = pending["data"]
    del _pending_verifications[email]
    return data


def cleanup_expired() -> None:
    """Remove expired entries."""
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _pending_verifications.items() if now > v["expires_at"]]
    for k in expired:
        del _pending_verifications[k]

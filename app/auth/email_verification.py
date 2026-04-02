import json
import random
from datetime import datetime, timedelta, timezone

import httpx
import redis

from app.config import settings

_OTP_TTL_SECONDS = 600  # 10 minutes
_KEY_PREFIX = "otp:"

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    """Get or create Redis connection."""
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


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
    """Store pending verification in Redis with 10-minute TTL."""
    r = _get_redis()
    value = json.dumps({"code": code, "data": registration_data})
    r.setex(f"{_KEY_PREFIX}{email}", _OTP_TTL_SECONDS, value)


def verify_code(email: str, code: str) -> dict | None:
    """Verify the code and return registration data if valid."""
    r = _get_redis()
    key = f"{_KEY_PREFIX}{email}"
    raw = r.get(key)
    if raw is None:
        return None

    pending = json.loads(raw)
    if pending["code"] != code:
        return None

    data = pending["data"]
    r.delete(key)
    return data


def cleanup_expired() -> None:
    """No-op: Redis TTL handles expiry automatically."""

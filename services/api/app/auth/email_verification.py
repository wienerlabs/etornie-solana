import json
import random
from datetime import datetime, timedelta, timezone

import redis

from app.config import settings
from app.notifications.email_transport import send_email

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
    """Email a 6-digit verification code via the shared SMTP transport.

    Returns True when the relay accepts the message. The registration
    endpoint turns a False into a user-facing error, so a sign-up never
    silently proceeds without the code having been sent.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_OTP_TTL_SECONDS)
    minutes = _OTP_TTL_SECONDS // 60
    subject = "Your Etornie verification code"
    body = (
        f"Hi {to_name or 'there'},\n\n"
        "Use this code to finish creating your Etornie account:\n\n"
        f"    {code}\n\n"
        f"It expires in {minutes} minutes "
        f"(at {expires_at.strftime('%H:%M UTC')}).\n\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "— Etornie"
    )
    return await send_email(
        to_email=to_email, to_name=to_name, subject=subject, body=body
    )


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

"""API-key authentication + per-key rate limiting for the public Q&A API.

Keys are random tokens prefixed ``etk_``; only their SHA-256 hash is stored.
Rate limiting is a fixed 60-second window counter in Redis, keyed by the
key's id. The limiter fails open (allows the request) if Redis is
unreachable — a notification/quota control must not take the API down.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone

import redis
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.public_api.models import ApiKey

logger = logging.getLogger(__name__)

API_KEY_PREFIX = "etk_"
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hex digest of a plaintext key (what we store and look up by)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Mint a new key. Returns ``(plaintext, sha256_hash)``.

    The plaintext is returned to the caller exactly once; only the hash is
    persisted.
    """
    raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw_key, hash_api_key(raw_key)


def enforce_rate_limit(api_key: ApiKey) -> None:
    """Per-key fixed-window (60s) limiter. Raises 429 when exceeded.

    Fails open on Redis errors so a transient cache outage never blocks
    legitimate traffic.
    """
    limit = api_key.rate_limit_per_minute
    if limit <= 0:  # 0 / negative means "no limit"
        return

    redis_key = f"apikey:ratelimit:{api_key.id}"
    try:
        client = _get_redis()
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, 60)
    except redis.RedisError as exc:
        logger.warning("Rate-limit check skipped (Redis unavailable): %s", exc)
        return

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please retry shortly.",
        )


async def require_api_key(
    raw_key: str | None = Security(_API_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Resolve and validate the ``X-API-Key`` header into an active ApiKey.

    401 when missing/unknown/revoked; 429 when the key is over its limit.
    """
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Send it in the X-API-Key header.",
        )

    api_key = await db.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == hash_api_key(raw_key),
            ApiKey.is_active.is_(True),
        )
    )
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )

    enforce_rate_limit(api_key)

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.flush()
    return api_key

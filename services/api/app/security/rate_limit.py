"""Redis-backed rate limiting middleware (issue #34).

A fixed-window counter per (route, identity) pair, stored in Redis so
the limit is correct across multiple worker processes — the whole
reason this is not an in-memory dict. Reuses the same Redis connection
already opened by app.auth.wallet_service (_get_redis()) rather than
introducing a second client or backend.

Keying: per authenticated user when a valid access token is present
(decoded here defensively — an invalid/expired token just falls back
to per-IP, the auth dependency further down the chain is what actually
rejects the request), per client IP otherwise. The app sits behind a
proxy, so the client IP is read from X-Forwarded-For (its first hop)
rather than the raw ASGI client tuple, which would just be the proxy.

A small custom middleware over the existing Redis client, rather than
slowapi: this keeps the 429 response shape identical to every other
error UserFacingError produces (see app/errors.py), and makes the
health-check exemption and the auth-surface allowlist trivial to read
in one place.
"""
from __future__ import annotations

import logging
from typing import Final

from jose import JWTError, jwt
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

logger = logging.getLogger(__name__)

# Paths exempt from rate limiting entirely — health/readiness probes
# must never be throttled, or an orchestrator could mistake a
# rate-limited box for an unhealthy one and kill it.
_EXEMPT_PATHS: Final[frozenset[str]] = frozenset({"/health"})

# Unauthenticated auth-surface endpoints that get the tighter
# rate_limit_auth_per_window limit instead of the global default.
# Prefix-matched so /auth/wallet/nonce and /auth/wallet/verify both
# land here under a single "/auth/wallet" entry.
_TIGHT_LIMIT_PREFIXES: Final[tuple[str, ...]] = (
    "/auth/login",
    "/auth/refresh",
    "/auth/wallet/nonce",
    "/auth/wallet/verify",
)


def _is_tight_limit_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _TIGHT_LIMIT_PREFIXES)


def _client_ip(header_map: dict[bytes, bytes], scope: Scope) -> str:
    """Resolve the client IP from X-Forwarded-For, falling back to the
    raw ASGI client tuple only when no proxy header is present (e.g.
    local dev without a reverse proxy in front)."""
    forwarded = header_map.get(b"x-forwarded-for")
    if forwarded:
        # The first entry is the original client; the proxy appends
        # its own hop(s) after that.
        return forwarded.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _identity_from_token(header_map: dict[bytes, bytes]) -> str | None:
    """Best-effort: return the authenticated user's id if the bearer
    token decodes cleanly. Any failure (missing header, malformed,
    expired, wrong signature) just means "no identity" — this
    middleware never rejects a request for a bad token, that is the
    real auth dependency's job further down the chain."""
    auth_header = header_map.get(b"authorization")
    if not auth_header:
        return None
    value = auth_header.decode("latin-1")
    if not value.startswith("Bearer "):
        return None
    token = value[len("Bearer ") :]
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


class RateLimitMiddleware:
    """Pure-ASGI middleware — see module docstring for the design.

    Implemented as raw ASGI rather than BaseHTTPMiddleware to match
    the existing RequestContextMiddleware convention in this codebase
    (app/observability.py) and to keep the Redis round-trip on the
    request path as cheap as possible (no extra layer of buffering).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        header_map = dict(scope.get("headers") or [])
        identity = _identity_from_token(header_map)
        scope_label = f"user:{identity}" if identity else f"ip:{_client_ip(header_map, scope)}"

        tight = _is_tight_limit_path(path)
        limit = (
            settings.rate_limit_auth_per_window
            if tight
            else settings.rate_limit_default_per_window
        )
        bucket = "auth" if tight else "default"

        try:
            from app.auth.wallet_service import _get_redis

            r = _get_redis()
            redis_key = f"rate_limit:{bucket}:{scope_label}"
            current = r.incr(redis_key)
            if current == 1:
                r.expire(redis_key, settings.rate_limit_window_seconds)
            ttl = r.ttl(redis_key)
        except Exception:  # noqa: BLE001
            # Redis unreachable: fail open. A rate limiter that can
            # take the whole API down on a cache outage is a worse
            # failure mode than temporarily unlimited traffic.
            logger.warning("rate limit check failed; allowing request", exc_info=True)
            await self.app(scope, receive, send)
            return

        if current > limit:
            retry_after = ttl if ttl and ttl > 0 else settings.rate_limit_window_seconds
            await _send_rate_limited_response(send, retry_after)
            return

        await self.app(scope, receive, send)


async def _send_rate_limited_response(send: Send, retry_after: int) -> None:
    import json

    body = json.dumps(
        {
            "error": "Too many requests. Please slow down and try again shortly.",
            "category": "rate_limit",
        }
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(retry_after).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})

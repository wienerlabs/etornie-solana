"""Redis-backed rate limiting middleware (issue #34).

A fixed-window counter per (bucket, identity), stored in Redis so the
limit is correct across multiple worker processes. It uses the same Redis
instance as the rest of the app (``settings.redis_url``) through
``redis.asyncio``: the synchronous client would block the event loop on
every request.

Each hit is one MULTI/EXEC round trip: ``SET key 0 EX <window> NX`` ->
``INCR key`` -> ``TTL key``. The key therefore always carries a TTL (the
old INCR-then-EXPIRE pair could leave a counter without one forever if the
process died in between). If Redis is slow or unreachable the request is
allowed (fail open); waiting is bounded by
``rate_limit_redis_timeout_seconds``.

Identity: the user id when a valid access token is present (decoded
defensively; a bad token just falls back to the IP, the auth dependency
further down is what rejects the request), the client IP otherwise.

Client IP: ``X-Forwarded-For`` is appended to by each proxy, so only the
entries on the right were written by infrastructure we run; the leftmost
entry is whatever the client sent. The IP is therefore the
``trusted_proxy_hops``-th entry from the right, never the leftmost. With
``trusted_proxy_hops = 0`` the header is ignored and the socket peer is
used.

Middleware order: Starlette makes the middleware added LAST the outermost
one. This middleware is registered first in ``app.main`` so it is the
innermost of the four, which means its 429 response still passes back
through RequestContext, SecurityHeaders and CORS and carries the request
id, the security headers and ``Access-Control-Allow-Origin`` (without it
the browser hides the 429 from the dashboard).

A small custom middleware rather than slowapi: the 429 body keeps the
same envelope as every other UserFacingError (see app/errors.py) and the
exemptions / tight-limit routes are readable in one place.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Final

import redis.asyncio as aioredis
from jose import JWTError, jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.errors import ErrorCategory

logger = logging.getLogger(__name__)

# Health/readiness probes must never be throttled, or an orchestrator
# could mistake a rate-limited box for an unhealthy one and kill it.
_EXEMPT_PATHS: Final[frozenset[str]] = frozenset({"/health"})

# Signature-verified webhooks: own, generous bucket (not exempt, so an
# unauthenticated flood still cannot burn unlimited signature checks).
_WEBHOOK_PREFIXES: Final[tuple[str, ...]] = (
    "/payments/stripe/webhook",
    "/solana/webhooks/",
    "/esign/webhook",
)

# Unauthenticated POSTs that get the tight limit. Prefix-matched:
#   /auth/login          also covers /auth/login/mfa (TOTP code guessing)
#   /auth/register       also covers /register/request (sends an OTP email
#                        on every call) and /register/verify (OTP guessing)
#   /zk/...              the operator signs and pays the fee for each call
_TIGHT_LIMIT_PREFIXES: Final[tuple[str, ...]] = (
    "/auth/login",
    "/auth/logout",
    "/auth/refresh",
    "/auth/register",
    "/auth/wallet/nonce",
    "/auth/wallet/verify",
    "/zk/verify-submit",
    "/zk/file-ownership/submit",
)


def _bucket_for_path(path: str) -> tuple[str, int]:
    if path.startswith(_WEBHOOK_PREFIXES):
        return "webhook", settings.rate_limit_webhook_per_window
    if path.startswith(_TIGHT_LIMIT_PREFIXES):
        return "auth", settings.rate_limit_auth_per_window
    return "default", settings.rate_limit_default_per_window


def resolve_client_ip(
    forwarded_for: str | None, peer: str | None, trusted_hops: int
) -> str:
    """Pick the client IP from the trusted (right) side of X-Forwarded-For.

    ``trusted_hops`` is the number of proxies we run. Falls back to the
    socket peer when the header is absent, trust is disabled (0) or the
    header has fewer entries than expected hops (a request that did not go
    through the whole proxy chain).
    """
    if trusted_hops > 0 and forwarded_for:
        entries = [e.strip() for e in forwarded_for.split(",") if e.strip()]
        if len(entries) >= trusted_hops:
            return entries[-trusted_hops]
    return peer or "unknown"


def _forwarded_for(scope: Scope) -> str | None:
    # Several X-Forwarded-For header lines are equivalent to one
    # comma-joined line; dict(headers) would keep only the last one.
    values = [
        value.decode("latin-1")
        for name, value in scope.get("headers") or []
        if name == b"x-forwarded-for"
    ]
    return ",".join(values) or None


def _identity_from_token(header_map: dict[bytes, bytes]) -> str | None:
    """Best-effort: the authenticated user's id if the bearer token decodes.

    Any failure just means "no identity"; this middleware never rejects a
    request for a bad token.
    """
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


_redis_client: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def _get_async_redis() -> aioredis.Redis:
    """Lazily create the async client, once per running event loop.

    Async connections are bound to the loop that opened them. A server has
    exactly one loop, so this is one client there; the per-loop check only
    matters for tests, which run every test on its own loop.
    """
    global _redis_client, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop is not loop:
        timeout = settings.rate_limit_redis_timeout_seconds
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
        )
        _redis_loop = loop
    return _redis_client


async def _hit(key: str) -> tuple[int, int]:
    """Count one request. Returns (count in this window, seconds left)."""
    r = _get_async_redis()
    window = settings.rate_limit_window_seconds
    async with r.pipeline(transaction=True) as pipe:
        _, current, ttl = await (
            pipe.set(key, 0, ex=window, nx=True).incr(key).ttl(key).execute()
        )
    if ttl < 0:
        # A counter without an expiry (should not happen any more): heal it.
        await r.expire(key, window)
        ttl = window
    return int(current), int(ttl)


class RateLimitMiddleware:
    """Pure-ASGI middleware, see the module docstring for the design."""

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
        if identity:
            who = f"user:{identity}"
        else:
            peer = (scope.get("client") or (None,))[0]
            who = "ip:" + resolve_client_ip(
                _forwarded_for(scope), peer, settings.trusted_proxy_hops
            )

        bucket, limit = _bucket_for_path(path)

        try:
            current, ttl = await _hit(f"rate_limit:{bucket}:{who}")
        except Exception:  # noqa: BLE001
            # Redis slow/unreachable: fail open. A limiter that can take
            # the API down on a cache outage is worse than briefly
            # unlimited traffic.
            logger.warning("rate limit check failed; allowing request", exc_info=True)
            await self.app(scope, receive, send)
            return

        if current > limit:
            retry_after = ttl if ttl > 0 else settings.rate_limit_window_seconds
            response = JSONResponse(
                {
                    "error": "Too many requests. Please slow down and try again shortly.",
                    "category": ErrorCategory.rate_limit.value,
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

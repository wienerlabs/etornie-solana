"""Security response-header middleware.

Adds a strict set of HTTP security headers to every response. The API
serves JSON only and is never framed or rendered as HTML, so the
Content-Security-Policy is maximally restrictive. HSTS is gated on the
deployment environment so it is never emitted over plain-HTTP local
development (a stray HSTS header on localhost can wedge a browser onto
https for that host).
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# A pure-JSON API loads no subresources and must never be framed.
_CSP = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)

# Disable browser features the API has no use for.
_PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(), usb=()"
)

_BASE_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Content-Security-Policy", _CSP),
    ("Permissions-Policy", _PERMISSIONS_POLICY),
    # Modern guidance: disable the legacy XSS auditor rather than enable it.
    ("X-XSS-Protection", "0"),
)

_HSTS_HEADER = (
    "Strict-Transport-Security",
    "max-age=63072000; includeSubDomains; preload",
)


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware that injects security headers on every response.

    Implemented at the ASGI layer (rather than BaseHTTPMiddleware) so it
    does not interfere with streaming responses or background tasks.
    """

    def __init__(self, app: ASGIApp, *, enable_hsts: bool) -> None:
        self.app = app
        self._headers: list[tuple[str, str]] = list(_BASE_HEADERS)
        if enable_hsts:
            self._headers.append(_HSTS_HEADER)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in self._headers:
                    headers[key] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)

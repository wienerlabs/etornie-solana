"""Base EUIPO HTTP client with rate limiting and error handling."""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.services.euipo.auth import get_auth_headers, invalidate_token

logger = logging.getLogger(__name__)


@dataclass
class _RateLimiter:
    """Sliding window rate limiter per API group."""

    # Limits: (max_calls, window_seconds)
    _limits: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "trademark_search": (25_000, 86_400),   # 25k/day
        "design_search": (35_000, 86_400),       # 35k/day
        "eutm_filing": (1_000, 3_600),            # 1k/hour
        "eud_filing": (1_000, 3_600),             # 1k/hour
        "goods_services": (1_000, 3_600),         # 1k/hour
        "document_repo": (1_000, 3_600),          # 1k/hour
        "me": (1_000, 3_600),                     # 1k/hour
    })
    _calls: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self, group: str) -> None:
        """Wait until a call is allowed under the rate limit."""
        if group not in self._limits:
            return

        max_calls, window = self._limits[group]

        async with self._lock:
            now = time.time()
            cutoff = now - window
            # Prune old entries
            self._calls[group] = [t for t in self._calls[group] if t > cutoff]

            if len(self._calls[group]) >= max_calls:
                oldest = self._calls[group][0]
                wait = oldest + window - now + 0.1
                logger.warning(
                    "EUIPO rate limit reached for %s, waiting %.1fs", group, wait
                )
                await asyncio.sleep(wait)
                # Re-prune after wait
                now = time.time()
                self._calls[group] = [t for t in self._calls[group] if t > now - window]

            self._calls[group].append(time.time())


_rate_limiter = _RateLimiter()


class EUIPOClientError(Exception):
    """Raised when an EUIPO API call fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"EUIPO API error {status_code}: {detail}")


async def euipo_request(
    method: str,
    path: str,
    *,
    rate_group: str,
    user_flow: bool = False,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Make an authenticated request to the EUIPO API.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE).
        path: API path (appended to base URL).
        rate_group: Rate limiter group key.
        user_flow: True for APIs requiring authorization_code (filing, docs, me).
        params: Query parameters.
        json_body: JSON request body.
        data: Form data body.
        files: File uploads.
        extra_headers: Additional headers (e.g. Application-Draft).
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON response.

    Raises:
        EUIPOClientError: On non-2xx responses.
    """
    await _rate_limiter.acquire(rate_group)

    url = f"{settings.euipo_base_url}{path}"
    headers = await get_auth_headers(user_flow=user_flow)

    if extra_headers:
        headers.update(extra_headers)

    # Don't send Accept: application/json for file uploads
    if files:
        headers.pop("Accept", None)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method,
            url,
            params=params,
            json=json_body,
            data=data,
            files=files,
            headers=headers,
        )

    # Handle 401 → refresh token and retry once
    if response.status_code == 401:
        invalidate_token()
        headers = await get_auth_headers(user_flow=user_flow)
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                files=files,
                headers=headers,
            )

    if response.status_code >= 400:
        detail = response.text[:500]
        try:
            err = response.json()
            detail = err.get("message", err.get("error_description", detail))
        except Exception:
            pass
        raise EUIPOClientError(response.status_code, detail)

    # Some endpoints return 204 No Content
    if response.status_code == 204:
        return {}

    return response.json()

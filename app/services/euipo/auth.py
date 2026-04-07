"""EUIPO OAuth2 / OpenID Connect authentication and token management.

Supports two flows:
- client_credentials: For search APIs (Trademark Search, Design Search, G&S)
- authorization_code: For filing/portfolio APIs (EUTM Filing, EUD Filing, Document Repo, Me)

Token TTL: 28800 seconds (8 hours).
"""

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings


@dataclass
class _TokenCache:
    """In-memory cache for an OAuth2 access token."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 60


# Separate caches for different grant types
_client_cache = _TokenCache()
_user_cache = _TokenCache()


async def get_client_credentials_token() -> str:
    """Get token via client_credentials flow (search APIs, G&S).

    No user identity — app-only access.
    """
    if _client_cache.is_valid:
        return _client_cache.access_token

    async with _client_cache._lock:
        if _client_cache.is_valid:
            return _client_cache.access_token

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.euipo_auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.euipo_api_key,
                    "client_secret": settings.euipo_api_secret,
                    "scope": "uid",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()

        _client_cache.access_token = data["access_token"]
        _client_cache.expires_at = time.time() + data.get("expires_in", 28800)
        return _client_cache.access_token


async def exchange_authorization_code(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for access + refresh tokens.

    Used for filing/portfolio APIs that need user identity.

    Args:
        code: Authorization code from EUIPO redirect.
        redirect_uri: The redirect URI used in the authorize request.

    Returns:
        Token response dict with access_token, refresh_token, expires_in.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.euipo_auth_url,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.euipo_api_key,
                "client_secret": settings.euipo_api_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()

    _user_cache.access_token = data["access_token"]
    _user_cache.refresh_token = data.get("refresh_token", "")
    _user_cache.expires_at = time.time() + data.get("expires_in", 28800)
    return data


async def get_user_token() -> str:
    """Get a valid user access token (authorization code flow).

    Auto-refreshes using refresh_token if expired.

    Raises:
        RuntimeError: If no user token is available (authorization_code needed).
    """
    if _user_cache.is_valid:
        return _user_cache.access_token

    async with _user_cache._lock:
        if _user_cache.is_valid:
            return _user_cache.access_token

        if not _user_cache.refresh_token:
            raise RuntimeError(
                "No EUIPO user session. Complete the authorization flow first "
                "via /euipo/auth/authorize."
            )

        # Refresh token
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.euipo_auth_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": _user_cache.refresh_token,
                    "client_id": settings.euipo_api_key,
                    "client_secret": settings.euipo_api_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()

        _user_cache.access_token = data["access_token"]
        if "refresh_token" in data:
            _user_cache.refresh_token = data["refresh_token"]
        _user_cache.expires_at = time.time() + data.get("expires_in", 28800)
        return _user_cache.access_token


async def get_auth_headers(*, user_flow: bool = False) -> dict[str, str]:
    """Return Authorization headers for EUIPO API calls.

    Args:
        user_flow: If True, use authorization_code token (filing APIs).
                   If False, use client_credentials token (search APIs).
    """
    if user_flow:
        token = await get_user_token()
    else:
        token = await get_client_credentials_token()

    return {
        "Authorization": f"Bearer {token}",
        "X-IBM-Client-Id": settings.euipo_api_key,
        "Accept": "application/json",
    }


def get_authorize_url(redirect_uri: str, scopes: list[str]) -> str:
    """Build the EUIPO authorization URL for user login.

    Args:
        redirect_uri: Where EUIPO redirects after login.
        scopes: OIDC scopes to request.

    Returns:
        Full authorization URL to redirect the user to.
    """
    base = settings.euipo_auth_url.replace("/accessToken", "/authorize")
    scope_str = " ".join(scopes)
    return (
        f"{base}?response_type=code"
        f"&client_id={settings.euipo_api_key}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope_str}"
    )


def invalidate_client_token() -> None:
    """Force client_credentials token refresh."""
    _client_cache.access_token = ""
    _client_cache.expires_at = 0.0


def invalidate_user_token() -> None:
    """Force user token refresh."""
    _user_cache.access_token = ""
    _user_cache.expires_at = 0.0


# Backwards compatibility
def invalidate_token() -> None:
    invalidate_client_token()
    invalidate_user_token()

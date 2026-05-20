"""EUIPO OAuth2 / OpenID Connect authentication and token management.

Two flows are supported:
- ``client_credentials``: search / G&S APIs (no user identity).
- ``authorization_code``: filing / portfolio / document APIs (user identity).

The user-flow token is persisted in ``euipo_oauth_token`` (singleton
row, id=1) so it survives server restarts. The bootstrap OIDC dance
only has to happen once per refresh_token lifetime; auto-refresh
keeps the access_token rolling underneath.

Concurrency: an in-process asyncio lock guards refresh storms; the DB
row's check constraint (id=1) prevents accidental duplicate sessions.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import async_session


# ---------------------------------------------------------------------------
# Client-credentials cache (search APIs) — still in-memory; no refresh_token.
# ---------------------------------------------------------------------------


@dataclass
class _ClientTokenCache:
    access_token: str = ""
    expires_at: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 60


_client_cache = _ClientTokenCache()


async def get_client_credentials_token() -> str:
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


# ---------------------------------------------------------------------------
# User-flow cache (filing APIs) — backed by euipo_oauth_token table.
# ---------------------------------------------------------------------------


_user_lock = asyncio.Lock()


async def _load_user_token_from_db() -> dict | None:
    """Read the singleton EUIPO user token row, if it exists.

    Returns a plain dict so callers do not have to hold a DB session.
    """
    from app.services.euipo.models import EuipoOAuthToken

    async with async_session() as db:
        row = (
            await db.execute(select(EuipoOAuthToken).where(EuipoOAuthToken.id == 1))
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "access_token": row.access_token,
            "refresh_token": row.refresh_token,
            "expires_at": row.expires_at,
            "scope": row.scope,
        }


async def _store_user_token(
    *,
    access_token: str,
    refresh_token: str,
    expires_in: int,
    scope: str | None = None,
) -> None:
    """Upsert the singleton EUIPO user token row.

    Postgres ``ON CONFLICT`` would be cleaner, but the operator-wide
    singleton (id=1) makes a load-or-insert-or-update flow equivalent
    and keeps the SQL portable across dialects (we still use SQLite in
    tests).
    """
    from app.services.euipo.models import EuipoOAuthToken

    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)
    async with async_session() as db:
        row = (
            await db.execute(select(EuipoOAuthToken).where(EuipoOAuthToken.id == 1))
        ).scalar_one_or_none()
        if row is None:
            row = EuipoOAuthToken(
                id=1,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=scope,
            )
            db.add(row)
        else:
            row.access_token = access_token
            # Some IdPs return a new refresh_token on every refresh —
            # rotate ours when one is present, otherwise keep the
            # original. EUIPO sandbox follows the rotation pattern, so
            # we must accept whatever shape arrives.
            if refresh_token:
                row.refresh_token = refresh_token
            row.expires_at = expires_at
            if scope is not None:
                row.scope = scope
        await db.commit()


def _is_db_token_valid(payload: dict | None) -> bool:
    if not payload:
        return False
    expires_at = payload["expires_at"]
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return bool(payload["access_token"]) and datetime.now(
        tz=timezone.utc
    ) < (expires_at - timedelta(seconds=60))


async def exchange_authorization_code(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for access + refresh tokens.

    Persists the resulting session to ``euipo_oauth_token`` so future
    backend processes (including the Stripe auto-submit path) can use
    it without re-doing the OIDC dance.
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

    await _store_user_token(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_in=data.get("expires_in", 28800),
        scope=data.get("scope"),
    )
    return data


async def get_user_token() -> str:
    """Return a valid EUIPO user access_token.

    Reads the persisted session from the DB, auto-refreshes if expired,
    and persists the rolled token back. Raises ``RuntimeError`` if no
    session has been bootstrapped via ``/euipo/auth/authorize`` yet.
    """
    async with _user_lock:
        payload = await _load_user_token_from_db()
        if _is_db_token_valid(payload):
            assert payload is not None
            return payload["access_token"]

        if payload is None or not payload.get("refresh_token"):
            raise RuntimeError(
                "No EUIPO user session. Complete the authorization flow "
                "first via /euipo/auth/authorize."
            )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.euipo_auth_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": payload["refresh_token"],
                    "client_id": settings.euipo_api_key,
                    "client_secret": settings.euipo_api_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()

        await _store_user_token(
            access_token=data["access_token"],
            # If EUIPO rotated the refresh_token, persist the new one;
            # otherwise keep the existing value.
            refresh_token=data.get("refresh_token", payload["refresh_token"]),
            expires_in=data.get("expires_in", 28800),
            scope=data.get("scope") or payload.get("scope"),
        )
        return data["access_token"]


async def get_auth_headers(*, user_flow: bool = False) -> dict[str, str]:
    """Return Authorization headers for an EUIPO API call.

    ``user_flow=True`` selects the persisted authorization_code session
    (filing APIs); ``False`` uses the in-memory client_credentials token
    (search APIs).
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
    base = settings.euipo_auth_url.replace("/accessToken", "/authorize")
    scope_str = " ".join(scopes)
    return (
        f"{base}?response_type=code"
        f"&client_id={settings.euipo_api_key}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope_str}"
    )


def invalidate_client_token() -> None:
    _client_cache.access_token = ""
    _client_cache.expires_at = 0.0


async def invalidate_user_token() -> None:
    """Wipe the persisted EUIPO user session.

    Forces the next call to ``get_user_token`` to fail with the "no
    session" error, prompting a fresh OIDC bootstrap. Use sparingly —
    e.g., after EUIPO rejects the current refresh_token as revoked.
    """
    from app.services.euipo.models import EuipoOAuthToken

    async with async_session() as db:
        row = (
            await db.execute(select(EuipoOAuthToken).where(EuipoOAuthToken.id == 1))
        ).scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.commit()


def invalidate_token() -> None:
    """Synchronous helper retained for callers that only need the client cache."""
    invalidate_client_token()

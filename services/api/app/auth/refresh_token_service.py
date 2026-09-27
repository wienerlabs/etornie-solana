"""Refresh token issuance, rotation, and reuse-detection (issue #35).

Refresh tokens are opaque random strings — never JWTs — because
rotation and reuse detection both require the server to look a
presented token up and mark it consumed, which a stateless JWT cannot
support. Only the sha256 hash of the raw token is ever persisted; the
raw value is returned to the client exactly once, at issuance or
rotation time, and never again.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
from app.config import settings

_TOKEN_BYTES = 48


class RefreshTokenError(Exception):
    """Raised when a presented refresh token is invalid, expired,
    already redeemed (reuse — the whole family gets revoked), or its
    family has been revoked."""


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _generate_raw_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


async def issue_new_family(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[str, uuid.UUID]:
    """Start a brand-new refresh token family (called at login).

    Returns (raw_token, family_id). The caller hands raw_token to the
    client as the refresh_token field; family_id is not exposed to the
    client, it is only used internally for the reuse-detection scope.
    """
    family_id = uuid.uuid4()
    raw_token = _generate_raw_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=_hash_token(raw_token),
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return raw_token, family_id


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def redeem_and_rotate(
    db: AsyncSession, raw_token: str
) -> tuple[str, uuid.UUID]:
    """Validate + rotate a presented refresh token.

    Returns (new_raw_token, user_id) on success. Raises
    RefreshTokenError on any failure — invalid/unknown token, expired,
    already redeemed (reuse: revokes the whole family before raising),
    or a revoked family. The caller (the /auth/refresh router) is
    responsible for mapping RefreshTokenError to a 401 response.
    """
    token_hash = _hash_token(raw_token)
    row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()

    if row is None:
        raise RefreshTokenError("refresh token not found")

    now = datetime.now(timezone.utc)

    if row.revoked_at is not None:
        raise RefreshTokenError("refresh token family has been revoked")

    if row.expires_at.replace(tzinfo=timezone.utc) < now:
        raise RefreshTokenError("refresh token expired")

    if row.redeemed_at is not None:
        # Reuse of an already-consumed token — either the legitimate
        # client or an attacker holding a stolen copy is replaying it;
        # we cannot tell which, so the safe answer is to revoke every
        # token in the family and force a fresh login.
        await _revoke_family(db, row.family_id)
        raise RefreshTokenError(
            "refresh token reuse detected; family revoked"
        )

    row.redeemed_at = now

    new_raw_token = _generate_raw_token()
    new_expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    new_row = RefreshToken(
        user_id=row.user_id,
        family_id=row.family_id,
        token_hash=_hash_token(new_raw_token),
        expires_at=new_expires_at,
    )
    db.add(new_row)
    await db.flush()

    return new_raw_token, row.user_id


async def revoke_family_by_token(db: AsyncSession, raw_token: str) -> None:
    """Revoke the family a presented token belongs to (logout).

    Silently no-ops if the token is unknown/already revoked — logout
    should never itself fail with an error the client has to handle.
    """
    token_hash = _hash_token(raw_token)
    row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if row is None:
        return
    await _revoke_family(db, row.family_id)

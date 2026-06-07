"""Persistence-side orchestration for TOTP two-factor authentication.

Thin layer over :mod:`app.auth.totp` that mutates the ``User`` row:
enroll (stash an encrypted pending secret), enable (verify possession and
mint recovery codes), disable, and second-factor verification used by the
login challenge. All functions ``flush`` so the caller's transaction sees
the change; commit stays with the request-scoped session dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import totp
from app.users.models import User


class TotpError(Exception):
    """Raised for invalid 2FA state transitions (bad code, not enrolled)."""


@dataclass(frozen=True)
class EnrollResult:
    secret: str
    otpauth_uri: str
    qr_data_url: str


async def begin_enrollment(db: AsyncSession, user: User) -> EnrollResult:
    """Generate and stash a fresh secret without enabling 2FA yet.

    Re-enrolling before enabling simply rotates the pending secret. If
    2FA is already enabled, the caller must disable it first — we refuse
    to silently overwrite a live secret.
    """

    if user.totp_enabled:
        raise TotpError("Two-factor authentication is already enabled")

    secret = totp.generate_secret()
    user.totp_secret = totp.encrypt_secret(secret)
    await db.flush()

    account = user.email or user.public_handle or str(user.id)
    uri = totp.provisioning_uri(secret, account)
    return EnrollResult(
        secret=secret,
        otpauth_uri=uri,
        qr_data_url=totp.qr_data_url(uri),
    )


async def enable(db: AsyncSession, user: User, code: str) -> list[str]:
    """Verify the pending secret with ``code`` and turn 2FA on.

    Returns the freshly minted plaintext recovery codes — shown to the
    user exactly once; only their hashes are persisted.
    """

    if user.totp_enabled:
        raise TotpError("Two-factor authentication is already enabled")
    if not user.totp_secret:
        raise TotpError("Start enrollment before enabling two-factor authentication")

    secret = totp.decrypt_secret(user.totp_secret)
    if not totp.verify_code(secret, code):
        raise TotpError("Invalid authentication code")

    recovery_codes = totp.generate_recovery_codes()
    user.totp_recovery_codes = totp.hash_recovery_codes(recovery_codes)
    user.totp_enabled = True
    await db.flush()
    return recovery_codes


async def disable(db: AsyncSession, user: User, code: str) -> None:
    """Turn 2FA off after proving possession (TOTP or recovery code)."""

    if not user.totp_enabled:
        raise TotpError("Two-factor authentication is not enabled")

    if not await verify_second_factor(db, user, code):
        raise TotpError("Invalid authentication code")

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_recovery_codes = None
    await db.flush()


async def verify_second_factor(db: AsyncSession, user: User, code: str) -> bool:
    """Accept either a valid TOTP code or an unused recovery code.

    A consumed recovery code is removed from the stored set so it cannot
    be reused.
    """

    if not user.totp_enabled or not user.totp_secret:
        return False

    secret = totp.decrypt_secret(user.totp_secret)
    if totp.verify_code(secret, code):
        return True

    updated = totp.consume_recovery_code(user.totp_recovery_codes, code)
    if updated is not None:
        user.totp_recovery_codes = updated
        await db.flush()
        return True

    return False


def recovery_codes_remaining(user: User) -> int:
    return totp.recovery_codes_remaining(user.totp_recovery_codes)

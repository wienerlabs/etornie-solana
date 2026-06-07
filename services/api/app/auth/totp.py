"""TOTP (RFC 6238) two-factor authentication primitives.

The shared secret is stored encrypted at rest. The encryption key is
derived deterministically from ``settings.jwt_secret`` via HKDF-SHA256,
so no additional secret has to be provisioned: rotating ``jwt_secret``
invalidates both sessions and stored TOTP secrets together, which is the
desired behaviour. The derived key never leaves this module.

Recovery codes let an admin who loses their authenticator device regain
access. They are generated once at enable time, shown to the user a
single time, and persisted only as bcrypt hashes — the same one-way
treatment as passwords.
"""

from __future__ import annotations

import base64
import io
import json
import secrets

import pyotp
import qrcode
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.fernet import Fernet, InvalidToken

from app.auth.utils import pwd_context
from app.config import settings

ISSUER = "Etornie"

# Number of recovery codes minted at enable time.
RECOVERY_CODE_COUNT = 10
# Bytes of entropy per recovery code before base32 encoding.
_RECOVERY_CODE_BYTES = 5

# Accept codes from the adjacent 30s window on each side to tolerate
# clock drift between the server and the authenticator app.
_VALID_WINDOW = 1


def _fernet() -> Fernet:
    """Build a Fernet instance from a key derived off ``jwt_secret``."""

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"etornie.totp.secret.v1",
        info=b"totp-secret-encryption",
    )
    raw = hkdf.derive(settings.jwt_secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(raw))


def generate_secret() -> str:
    """Return a fresh base32 TOTP secret."""

    return pyotp.random_base32()


def encrypt_secret(secret: str) -> str:
    """Encrypt a base32 secret for storage."""

    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Decrypt a stored secret. Raises ``InvalidToken`` if tampered."""

    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def provisioning_uri(secret: str, account_name: str) -> str:
    """Build the ``otpauth://`` URI an authenticator app consumes."""

    return pyotp.TOTP(secret).provisioning_uri(
        name=account_name,
        issuer_name=ISSUER,
    )


def qr_data_url(uri: str) -> str:
    """Render a provisioning URI to a base64 PNG ``data:`` URL."""

    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def verify_code(secret: str, code: str) -> bool:
    """Validate a 6-digit TOTP code against the secret."""

    cleaned = code.strip().replace(" ", "")
    if not cleaned.isdigit():
        return False
    return pyotp.TOTP(secret).verify(cleaned, valid_window=_VALID_WINDOW)


def generate_recovery_codes() -> list[str]:
    """Return a fresh batch of human-friendly recovery codes."""

    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = base64.b32encode(secrets.token_bytes(_RECOVERY_CODE_BYTES))
        token = raw.decode("ascii").rstrip("=")
        codes.append(f"{token[:4]}-{token[4:]}")
    return codes


def hash_recovery_codes(codes: list[str]) -> str:
    """Hash a batch of recovery codes into a JSON-serialised store."""

    hashes_ = [pwd_context.hash(_normalize_recovery(code)) for code in codes]
    return json.dumps(hashes_)


def _normalize_recovery(code: str) -> str:
    return code.strip().upper().replace("-", "").replace(" ", "")


def consume_recovery_code(stored: str | None, code: str) -> str | None:
    """Verify a recovery code against the stored hashes.

    Returns the updated JSON store (with the used hash removed) on a
    match, or ``None`` if the code does not match any stored hash. The
    caller persists the returned store so each recovery code is
    single-use.
    """

    if not stored:
        return None
    try:
        hashes_: list[str] = json.loads(stored)
    except (json.JSONDecodeError, TypeError):
        return None

    candidate = _normalize_recovery(code)
    if not candidate:
        return None

    for index, hashed in enumerate(hashes_):
        if pwd_context.verify(candidate, hashed):
            remaining = hashes_[:index] + hashes_[index + 1 :]
            return json.dumps(remaining)
    return None


def recovery_codes_remaining(stored: str | None) -> int:
    """Count how many unused recovery codes remain."""

    if not stored:
        return 0
    try:
        return len(json.loads(stored))
    except (json.JSONDecodeError, TypeError):
        return 0


__all__ = [
    "ISSUER",
    "RECOVERY_CODE_COUNT",
    "InvalidToken",
    "consume_recovery_code",
    "decrypt_secret",
    "encrypt_secret",
    "generate_recovery_codes",
    "generate_secret",
    "hash_recovery_codes",
    "provisioning_uri",
    "qr_data_url",
    "recovery_codes_remaining",
    "verify_code",
]

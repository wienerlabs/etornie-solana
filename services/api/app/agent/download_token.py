"""HMAC-signed download tokens for agent_upload files.

The agent's chat surface returns plain ``http://.../agent/uploads/<id>/download``
links that the user clicks straight from the rendered message. A direct
browser GET cannot carry the JWT bearer the rest of the API requires,
so we attach a short-lived signed token to the URL: it binds the
signature to (upload_id, expires_at) using the same JWT_SECRET as the
auth layer, so a leaked token only works on that one file and only
until it expires.

This is **not** a replacement for the JWT auth — it is an additional
accepted credential. The download endpoint still falls back to JWT
when no token is supplied, so existing API consumers keep working.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

from app.config import settings


# Default lifetime for download links surfaced by the agent. Long enough
# that a user who lets the chat sit for a while can still click; short
# enough that a leaked link is not useful long-term.
DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _sign(message: bytes) -> bytes:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()


def make_download_token(
    upload_id: uuid.UUID,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Build a signed token for ``upload_id`` valid for ``ttl_seconds``.

    Token shape: ``<exp_unix>.<base64url(hmac_sha256)>``. The upload_id
    is bound into the HMAC payload, not the token body — the verifier
    derives the same payload from the URL path.
    """
    expires_at = int(time.time()) + max(ttl_seconds, 1)
    payload = f"{upload_id}:{expires_at}".encode("utf-8")
    sig = _sign(payload)
    return f"{expires_at}.{_b64url(sig)}"


def verify_download_token(upload_id: uuid.UUID, token: str) -> bool:
    """Constant-time validation. Returns True only when the signature
    matches and the token has not yet expired."""
    if not token or "." not in token:
        return False
    exp_str, sig_b64 = token.split(".", 1)
    try:
        expires_at = int(exp_str)
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False
    payload = f"{upload_id}:{expires_at}".encode("utf-8")
    expected = _sign(payload)
    try:
        provided = _b64url_decode(sig_b64)
    except Exception:
        return False
    return hmac.compare_digest(expected, provided)

"""Operator key security layer — Fernet-at-rest + audit logging.

This module wraps the raw key material handling so callers do not
need to know about the encryption scheme. Two ways to provide the
key file:

1. Plaintext JSON byte array, e.g.
   ``[12, 34, 56, ...]`` — the legacy format.
2. Fernet-encrypted blob, recognised by the ``etornie-key-v1:``
   prefix. The remainder is a Fernet token whose plaintext is the
   JSON byte array above. Activated when ``OPERATOR_KEY_MASTER_KEY``
   env var is set; the master key is a 32-byte url-safe base64
   string generated via ``Fernet.generate_key()``.

Audit log: every load attempt — whether for sign / verify / inspect
— writes one row to ``operator_key_access_log`` (table created in
migration f6a7b8c9d0e1). The row carries caller_context + op_kind +
success + a 500-char free-form note (used for failure reasons).
Audit writes use a fresh session so a failing load does not also
lose its audit row.

Rotation: the loader caches NOTHING. Rotating the underlying file +
master key takes effect on the next request; in-flight subprocesses
holding the materialised /tmp file path continue to use the old key
until they finish.
"""
from __future__ import annotations

import logging
import os
from typing import Final

logger = logging.getLogger(__name__)


_FERNET_PREFIX: Final[str] = "etornie-key-v1:"


class OperatorKeyError(RuntimeError):
    """Raised when key loading / decryption fails."""


def decrypt_if_needed(raw: str) -> str:
    """Return the plaintext key JSON.

    If ``raw`` carries the Fernet prefix, ``OPERATOR_KEY_MASTER_KEY``
    is required and the blob is decrypted. Otherwise ``raw`` is
    returned unchanged.

    The cryptography import is local so an installation without
    ``cryptography`` only sees the import error when actually
    decrypting (not on every module load).
    """
    if not raw.startswith(_FERNET_PREFIX):
        return raw
    master = os.environ.get("OPERATOR_KEY_MASTER_KEY")
    if not master:
        raise OperatorKeyError(
            "Encrypted operator key found but OPERATOR_KEY_MASTER_KEY "
            "is not set. Either rotate the key file back to plaintext "
            "or supply the master key as an env var."
        )
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:  # noqa: BLE001
        raise OperatorKeyError(
            "Encrypted operator key requires the ``cryptography`` "
            "package to be installed."
        ) from exc
    payload = raw[len(_FERNET_PREFIX) :].encode("utf-8")
    try:
        plaintext = Fernet(master.encode("utf-8")).decrypt(payload)
    except InvalidToken as exc:
        raise OperatorKeyError(
            "Operator key decryption failed: master key does not "
            "match the encrypted blob."
        ) from exc
    except ValueError as exc:
        raise OperatorKeyError(
            f"Operator key decryption failed: {exc}"
        ) from exc
    return plaintext.decode("utf-8")


def encrypt_plaintext(plaintext: str) -> str:
    """Helper used by the rotation tool — never called at runtime."""
    master = os.environ.get("OPERATOR_KEY_MASTER_KEY")
    if not master:
        raise OperatorKeyError(
            "Set OPERATOR_KEY_MASTER_KEY before encrypting a key."
        )
    from cryptography.fernet import Fernet

    token = Fernet(master.encode("utf-8")).encrypt(plaintext.encode("utf-8"))
    return _FERNET_PREFIX + token.decode("utf-8")


def log_operator_access(
    *,
    caller_context: str,
    op_kind: str,
    success: bool,
    note: str | None = None,
) -> None:
    """Append one row to operator_key_access_log.

    Best-effort: a failing audit write logs at WARNING and does not
    propagate, so the calling code path (which already may have hit
    a key error) does not get smothered by an audit failure.
    """
    # Lazy imports keep this module importable from circuit / agent
    # contexts that do not have the full DB graph wired up.
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.database import async_session
    from app.security.models import OperatorKeyAccessLog

    async def _persist() -> None:
        try:
            async with async_session() as session:  # type: AsyncSession
                row = OperatorKeyAccessLog(
                    caller_context=caller_context[:255],
                    op_kind=op_kind[:20],
                    success=success,
                    note=(note[:500] if note else None),
                )
                session.add(row)
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.warning(
                "operator key audit write failed", exc_info=True
            )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Best-effort fire-and-forget inside an event loop so we
            # do not block the caller. Tests that need synchronous
            # audit assertions call _persist() directly.
            loop.create_task(_persist())
        else:
            loop.run_until_complete(_persist())
    except RuntimeError:
        # No event loop in this thread (e.g. a CLI script) — just
        # spin up a fresh loop for the one write.
        asyncio.run(_persist())

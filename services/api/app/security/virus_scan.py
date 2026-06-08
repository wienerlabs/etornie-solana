"""ClamAV malware scanning for untrusted uploads (#55).

Every file an untrusted client uploads — case documents, agent chat
attachments, avatars, UK IPO mark images — is streamed to a ClamAV daemon
(clamd) before it is persisted or indexed, so a matched file never reaches
disk or the RAG index.

The clamd protocol library is synchronous, so the INSTREAM call runs in a
worker thread (``asyncio.to_thread``) to keep the event loop free.

Posture
- Disabled by default (``CLAMAV_ENABLED=false``) so local dev needs no
  daemon; ``scan_upload`` is then a no-op.
- When enabled, a daemon that is unreachable or errors is treated as
  FAIL-CLOSED — the upload is rejected (503) rather than waved through, so a
  P0 control cannot be silently bypassed by taking the scanner offline.

Errors are surfaced as :class:`app.errors.UserFacingError` subclasses, so the
exception handler registered in ``app.main`` turns them into a clean response
automatically — callers just ``await scan_upload(...)`` with no try/except.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.errors import ErrorCategory, UserFacingError

logger = logging.getLogger(__name__)


class InfectedFileError(UserFacingError):
    """Raised when ClamAV matches a signature in an uploaded file."""

    def __init__(self, signature: str, *, filename: str | None = None) -> None:
        super().__init__(
            "This file was rejected by our malware scanner and was not stored.",
            technical_detail=f"clamav signature={signature!r} filename={filename!r}",
            category=ErrorCategory.validation,
            http_status=400,
        )
        self.signature = signature


class VirusScanUnavailableError(UserFacingError):
    """Raised (fail-closed) when scanning is enabled but cannot complete."""

    def __init__(self, technical_detail: str) -> None:
        super().__init__(
            "File scanning is temporarily unavailable. Please try again shortly.",
            technical_detail=technical_detail,
            category=ErrorCategory.validation,
            http_status=503,
        )


def _scan_stream(data: bytes) -> tuple[str, str | None]:
    """Blocking clamd INSTREAM scan. Returns ``(status, signature)``.

    ``status`` is ``"OK"``, ``"FOUND"`` or ``"ERROR"`` per the clamd
    protocol. ``clamd`` is imported lazily so the module stays importable
    (and dev/tests run) without the package when scanning is disabled.
    """
    import io

    import clamd

    client = clamd.ClamdNetworkSocket(
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout=settings.clamav_timeout,
    )
    # clamd returns e.g. {"stream": ("FOUND", "Eicar-Test-Signature")}
    # or {"stream": ("OK", None)}.
    status, signature = client.instream(io.BytesIO(data))["stream"]
    return status, signature


async def scan_upload(data: bytes, *, filename: str | None = None) -> None:
    """Scan ``data`` for malware; return ``None`` when clean.

    No-op when ``CLAMAV_ENABLED`` is false. Raises :class:`InfectedFileError`
    when a signature matches, or :class:`VirusScanUnavailableError`
    (fail-closed) when an enabled scan cannot complete.
    """
    if not settings.clamav_enabled:
        return

    try:
        status, signature = await asyncio.to_thread(_scan_stream, data)
    except Exception as exc:
        # Any failure to reach / complete the scan fails closed: a P0
        # control must not be bypassed just because the daemon is down.
        logger.error("ClamAV scan failed (fail-closed) for %s: %s", filename, exc)
        raise VirusScanUnavailableError(f"{type(exc).__name__}: {exc}") from exc

    if status == "FOUND":
        logger.warning("ClamAV rejected upload %s: %s", filename, signature)
        raise InfectedFileError(signature or "unknown", filename=filename)
    if status != "OK":
        logger.error("ClamAV returned %s for %s: %s", status, filename, signature)
        raise VirusScanUnavailableError(f"clamd status={status} signature={signature}")

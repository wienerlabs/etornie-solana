"""Yousign API v3 client (e-signature provider, issue #63).

Thin async HTTP layer over the Yousign v3 REST API. Every network call
to Yousign lives here so the service layer stays provider-agnostic; if a
second provider is added later only this module is duplicated.

Flow (https://developers.yousign.com):
  POST /signature_requests                     -> create (draft)
  POST /signature_requests/{id}/documents      -> upload signable PDF
  POST /signature_requests/{id}/signers        -> add signer + field
  POST /signature_requests/{id}/activate       -> send (emails signer)
  GET  /signature_requests/{id}                -> read status + links
  GET  /signature_requests/{id}/documents/{doc}/download -> signed PDF

Webhook payloads carry an ``X-Yousign-Signature-256: sha256=<hmac>``
header verified against the configured webhook secret.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.config import settings
from app.errors import ErrorCategory, UserFacingError

logger = logging.getLogger(__name__)

# Where the signature box is stamped on the PDF. These are layout
# defaults (points from the lower-left of page 1), not business data —
# a sensible bottom-left placement that works for affidavit/declaration
# style documents.
_FIELD_PAGE = 1
_FIELD_X = 80
_FIELD_Y = 80
_FIELD_WIDTH = 120
_FIELD_HEIGHT = 50

_TIMEOUT = httpx.Timeout(30.0)


class EsignError(UserFacingError):
    """Domain-level e-signature failure surfaced to the caller."""

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(
            user_message=user_message
            or "We could not process this signature request. Please try again.",
            technical_detail=message,
            category=ErrorCategory.unknown,
            http_status=http_status,
        )
        self.args = (message,)


def is_configured() -> bool:
    return bool(settings.yousign_api_key)


def _require_configured() -> None:
    if not settings.yousign_api_key:
        raise EsignError(
            "Yousign is not configured (YOUSIGN_API_KEY is empty).",
            user_message="E-signature is not available on this server.",
            http_status=503,
        )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.yousign_api_key}"}


def _base() -> str:
    return settings.yousign_base_url.rstrip("/")


def _raise_for(resp: httpx.Response, action: str) -> None:
    if resp.is_success:
        return
    body = resp.text[:400]
    logger.warning("Yousign %s failed %s: %s", action, resp.status_code, body)
    raise EsignError(
        f"Yousign {action} failed ({resp.status_code}): {body}",
        user_message="The e-signature provider rejected the request.",
        http_status=502,
    )


async def create_signature_request(*, name: str) -> str:
    """Create a draft signature request; return its provider id."""
    _require_configured()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_base()}/signature_requests",
            headers=_headers(),
            json={
                "name": name,
                "delivery_mode": "email",
                "timezone": "Europe/Zurich",
            },
        )
    _raise_for(resp, "create signature request")
    return resp.json()["id"]


async def upload_document(
    *, request_id: str, file_bytes: bytes, filename: str
) -> str:
    """Upload the signable PDF; return the provider document id."""
    _require_configured()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_base()}/signature_requests/{request_id}/documents",
            headers=_headers(),
            files={"file": (filename, file_bytes, "application/pdf")},
            data={"nature": "signable_document"},
        )
    _raise_for(resp, "upload document")
    return resp.json()["id"]


async def add_signer(
    *,
    request_id: str,
    document_id: str,
    first_name: str,
    last_name: str,
    email: str,
    locale: str = "en",
) -> str:
    """Add the signer with a signature field; return the signer id."""
    _require_configured()
    payload: dict[str, Any] = {
        "info": {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "locale": locale,
        },
        "signature_level": "electronic_signature",
        "signature_authentication_mode": "no_otp",
        "fields": [
            {
                "type": "signature",
                "document_id": document_id,
                "page": _FIELD_PAGE,
                "x": _FIELD_X,
                "y": _FIELD_Y,
                "width": _FIELD_WIDTH,
                "height": _FIELD_HEIGHT,
            }
        ],
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_base()}/signature_requests/{request_id}/signers",
            headers=_headers(),
            json=payload,
        )
    _raise_for(resp, "add signer")
    return resp.json()["id"]


async def activate(*, request_id: str) -> dict[str, Any]:
    """Activate (send) the request; return the activated payload."""
    _require_configured()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_base()}/signature_requests/{request_id}/activate",
            headers=_headers(),
        )
    _raise_for(resp, "activate signature request")
    return resp.json()


async def get_signature_request(*, request_id: str) -> dict[str, Any]:
    _require_configured()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_base()}/signature_requests/{request_id}",
            headers=_headers(),
        )
    _raise_for(resp, "get signature request")
    return resp.json()


async def download_signed_document(
    *, request_id: str, document_id: str
) -> bytes:
    """Download the completed (signed) PDF bytes."""
    _require_configured()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_base()}/signature_requests/{request_id}/documents/"
            f"{document_id}/download",
            headers=_headers(),
        )
    _raise_for(resp, "download signed document")
    return resp.content


def extract_signature_link(activated: dict[str, Any]) -> str | None:
    """Pull the first signer's hosted signing link from an activate/get
    payload, tolerating the two shapes Yousign returns."""
    signers = activated.get("signers") or []
    if signers and isinstance(signers, list):
        link = signers[0].get("signature_link")
        if link:
            return link
    return activated.get("signature_link")


def verify_webhook(payload: bytes, signature_header: str | None) -> bool:
    """Verify the ``X-Yousign-Signature-256`` HMAC-SHA256 header.

    Fails closed: returns False when no secret is configured or the
    header is missing/malformed.
    """
    secret = settings.yousign_webhook_secret
    if not secret or not signature_header:
        return False
    expected = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature_header.strip())

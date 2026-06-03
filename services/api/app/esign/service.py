"""E-signature service layer (issue #63).

Orchestrates the Yousign provider client and the local
``SignatureRequest`` rows: turns a stored case PDF into an activated
signature request, and reconciles provider webhooks back onto the row
(downloading the signed PDF into a new ``Document`` on completion).
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.config import settings
from app.documents.models import Document
from app.documents.service import create_document
from app.esign import yousign_client
from app.esign.models import (
    SignatureProvider,
    SignatureRequest,
    SignatureRequestStatus,
)
from app.esign.yousign_client import EsignError
from app.users.models import User

logger = logging.getLogger(__name__)


# Yousign's name fields reject anything outside letters, spaces,
# hyphens and apostrophes (e.g. underscores or digits in an
# auto-generated wallet handle like "etornie_CBDjvUkZ"). Replace the
# rest with spaces before splitting.
_NAME_DISALLOWED = re.compile(r"[^A-Za-zÀ-ÖØ-öø-ÿ' -]+")


def _split_name(full_name: str) -> tuple[str, str]:
    """Split a display name into provider-safe (first, last).

    Yousign requires both and rejects unauthorized characters; we
    sanitise to its allowed set and collapse single-token names so the
    call never fails on a missing or invalid last name.
    """
    cleaned = _NAME_DISALLOWED.sub(" ", full_name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    parts = cleaned.split()
    if not parts:
        return "Client", "Client"
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


async def create_signature_request_for_document(
    db: AsyncSession,
    *,
    case: Case,
    document: Document,
    signer: User,
    subject: str | None = None,
) -> SignatureRequest:
    """Send a case document to its client for e-signature via Yousign.

    Reads the stored PDF, creates + activates a Yousign signature
    request, and persists a ``SignatureRequest`` row. On provider failure
    the row is saved with ``status=error`` and the error is re-raised.
    """
    if not signer.email:
        raise EsignError(
            f"Signer {signer.id} has no email; cannot send for signature.",
            user_message=(
                "The signer has no email address on file. Add an email "
                "before sending the document for signature."
            ),
            http_status=400,
        )
    if document.case_id != case.id:
        raise EsignError(
            "Document does not belong to the case.",
            user_message="This document is not part of the case.",
            http_status=400,
        )
    if not document.file_path or not os.path.isfile(document.file_path):
        raise EsignError(
            f"Document {document.id} file is missing on disk.",
            user_message="The document file could not be found on the server.",
            http_status=404,
        )

    first_name, last_name = _split_name(signer.full_name)
    title = subject or f"Signature required — {document.filename}"

    row = SignatureRequest(
        case_id=case.id,
        source_document_id=document.id,
        signer_user_id=signer.id,
        provider=SignatureProvider.yousign,
        status=SignatureRequestStatus.draft,
        signer_email=signer.email,
        signer_name=signer.full_name or signer.email,
        subject=title,
    )
    db.add(row)
    await db.flush()

    try:
        with open(document.file_path, "rb") as fh:
            pdf_bytes = fh.read()

        request_id = await yousign_client.create_signature_request(name=title)
        row.provider_request_id = request_id

        document_id = await yousign_client.upload_document(
            request_id=request_id,
            file_bytes=pdf_bytes,
            filename=document.filename or "document.pdf",
        )
        row.provider_document_id = document_id

        signer_id = await yousign_client.add_signer(
            request_id=request_id,
            document_id=document_id,
            first_name=first_name,
            last_name=last_name,
            email=signer.email,
        )
        row.provider_signer_id = signer_id

        activated = await yousign_client.activate(request_id=request_id)
        row.signing_url = yousign_client.extract_signature_link(activated)
        row.status = SignatureRequestStatus.ongoing
        row.error = None
    except EsignError as exc:
        row.status = SignatureRequestStatus.error
        row.error = str(exc)
        await db.flush()
        raise

    await db.flush()
    return row


async def get_request(
    db: AsyncSession, request_id: uuid.UUID
) -> SignatureRequest | None:
    return (
        await db.execute(
            select(SignatureRequest).where(SignatureRequest.id == request_id)
        )
    ).scalar_one_or_none()


async def list_for_case(
    db: AsyncSession, case_id: uuid.UUID
) -> list[SignatureRequest]:
    return list(
        (
            await db.execute(
                select(SignatureRequest)
                .where(SignatureRequest.case_id == case_id)
                .order_by(SignatureRequest.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Webhook reconciliation
# ---------------------------------------------------------------------------

# Yousign webhook event_name -> terminal status.
_TERMINAL_EVENTS = {
    "signature_request.done": SignatureRequestStatus.signed,
    "signature_request.declined": SignatureRequestStatus.declined,
    "signature_request.expired": SignatureRequestStatus.expired,
}


async def _store_signed_document(
    db: AsyncSession, row: SignatureRequest
) -> uuid.UUID | None:
    """Download the signed PDF from Yousign and persist it as a Document."""
    if not (row.provider_request_id and row.provider_document_id):
        return None
    signed_bytes = await yousign_client.download_signed_document(
        request_id=row.provider_request_id,
        document_id=row.provider_document_id,
    )
    case_dir = os.path.join(settings.upload_dir, str(row.case_id))
    os.makedirs(case_dir, exist_ok=True)
    base_name = "document.pdf"
    if row.source_document_id is not None:
        src = (
            await db.execute(
                select(Document).where(Document.id == row.source_document_id)
            )
        ).scalar_one_or_none()
        if src is not None and src.filename:
            base_name = src.filename
    filename = f"signed_{base_name}"
    file_path = os.path.join(case_dir, f"{uuid.uuid4()}_{filename}")
    with open(file_path, "wb") as fh:
        fh.write(signed_bytes)

    signed_doc = await create_document(
        db,
        case_id=row.case_id,
        uploaded_by=row.signer_user_id,
        filename=filename,
        file_path=file_path,
        file_type="application/pdf",
        file_size=len(signed_bytes),
        document_type="signed_document",
    )
    return signed_doc.id


async def handle_webhook(db: AsyncSession, event: dict[str, Any]) -> dict[str, Any]:
    """Reconcile a verified Yousign webhook event onto its row.

    Idempotent: a redelivered ``done`` event on an already-signed row is
    a no-op (the signed document is only stored once).
    """
    event_name = event.get("event_name")
    target = _TERMINAL_EVENTS.get(event_name or "")
    if target is None:
        return {"handled": False, "reason": "ignored_event", "event": event_name}

    sr = (event.get("data") or {}).get("signature_request") or {}
    provider_request_id = sr.get("id")
    if not provider_request_id:
        return {"handled": False, "reason": "missing_signature_request_id"}

    row = (
        await db.execute(
            select(SignatureRequest).where(
                SignatureRequest.provider_request_id == provider_request_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"handled": False, "reason": "request_not_found"}

    if row.status == SignatureRequestStatus.signed:
        return {"handled": True, "reason": "already_signed"}

    if target is SignatureRequestStatus.signed:
        if row.signed_document_id is None:
            signed_id = await _store_signed_document(db, row)
            if signed_id is not None:
                row.signed_document_id = signed_id
        row.status = SignatureRequestStatus.signed
        row.error = None
    else:
        row.status = target

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "handled": True,
        "signature_request_id": str(row.id),
        "status": row.status.value,
    }

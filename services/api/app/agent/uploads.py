"""Storage and CRUD for files attached inside an agent session.

Files land on disk under ``<upload_dir>/agent/<session_id>/<uuid>_<name>``.
The on-disk layout is the source of truth — DB rows in ``agent_upload``
carry the metadata, server-computed sha256, and any ZK ownership claim
the user attached at upload time.

The upload module is auth-agnostic. The router enforces session
ownership; this module only does I/O and DB writes.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import AgentUpload, AgentUploadStatus
from app.config import settings


_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PDA_LEN_RANGE = (32, 44)
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._\-]")
_FILENAME_MAX_LEN = 200


class UploadStorageError(Exception):
    """Raised when the file cannot be persisted to disk or DB."""


def is_hex64(value: str | None) -> bool:
    return value is not None and bool(_HEX64_RE.match(value))


def _agent_session_dir(session_id: uuid.UUID) -> str:
    return os.path.join(settings.upload_dir, "agent", str(session_id))


def _safe_filename(original: str) -> str:
    """Strip path separators and unsafe chars; fall back to a uuid name."""
    base = os.path.basename(original or "").strip()
    if not base:
        return "unnamed"
    cleaned = _FILENAME_SAFE_RE.sub("_", base)
    if len(cleaned) > _FILENAME_MAX_LEN:
        root, ext = os.path.splitext(cleaned)
        keep = _FILENAME_MAX_LEN - len(ext)
        cleaned = root[: max(keep, 1)] + ext
    return cleaned or "unnamed"


async def store_upload(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    original_filename: str,
    file_bytes: bytes,
    mime_type: str | None,
    expected_document_type: str | None,
    file_hash_hex: str | None,
    ownership_commitment_hex: str | None,
) -> AgentUpload:
    """Persist file bytes to disk and create the DB row.

    Validates ZK ownership-claim consistency:
      * ``file_hash_hex`` must equal the server-computed sha256 of the
        bytes; mismatch is treated as a client error.
      * ``file_hash_hex`` and ``ownership_commitment_hex`` must be
        supplied together or not at all.
    """
    if (file_hash_hex is None) != (ownership_commitment_hex is None):
        raise UploadStorageError(
            "file_hash_hex and ownership_commitment_hex must be supplied "
            "together or not at all"
        )
    if file_hash_hex is not None and not is_hex64(file_hash_hex):
        raise UploadStorageError(
            "file_hash_hex must be a 64-char hex string (sha256 of the file)"
        )
    if ownership_commitment_hex is not None and not is_hex64(
        ownership_commitment_hex
    ):
        raise UploadStorageError(
            "ownership_commitment_hex must be a 64-char hex string "
            "(32-byte Poseidon output)"
        )

    server_sha256 = hashlib.sha256(file_bytes).hexdigest()
    if file_hash_hex is not None and file_hash_hex.lower() != server_sha256:
        raise UploadStorageError(
            "file_hash_hex does not match sha256 of uploaded bytes "
            f"(client={file_hash_hex.lower()}, server={server_sha256})"
        )

    safe_name = _safe_filename(original_filename)
    target_dir = _agent_session_dir(session_id)
    os.makedirs(target_dir, exist_ok=True)
    stored_filename = f"{uuid.uuid4()}_{safe_name}"
    stored_path = os.path.join(target_dir, stored_filename)

    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    upload = AgentUpload(
        session_id=session_id,
        user_id=user_id,
        original_filename=safe_name,
        stored_path=stored_path,
        mime_type=mime_type,
        size_bytes=len(file_bytes),
        sha256_hex=server_sha256,
        status=AgentUploadStatus.uploaded,
        expected_document_type=expected_document_type,
        file_hash_hex=(
            file_hash_hex.lower() if file_hash_hex is not None else None
        ),
        ownership_commitment_hex=(
            ownership_commitment_hex.lower()
            if ownership_commitment_hex is not None
            else None
        ),
    )
    db.add(upload)
    await db.flush()
    await db.refresh(upload)
    return upload


async def list_session_uploads(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    include_cancelled: bool = False,
) -> list[AgentUpload]:
    stmt = (
        select(AgentUpload)
        .where(AgentUpload.session_id == session_id)
        .order_by(AgentUpload.created_at.asc())
    )
    if not include_cancelled:
        stmt = stmt.where(AgentUpload.status != AgentUploadStatus.cancelled)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_upload(
    db: AsyncSession,
    upload_id: uuid.UUID,
) -> AgentUpload | None:
    result = await db.execute(
        select(AgentUpload).where(AgentUpload.id == upload_id)
    )
    return result.scalar_one_or_none()


async def cancel_upload(
    db: AsyncSession,
    upload: AgentUpload,
) -> AgentUpload:
    """Soft-cancel an upload and remove the on-disk file.

    The DB row stays so the chat history references remain readable, but
    the bytes are deleted to release storage. ``stored_path`` is preserved
    for audit; downstream code must check ``status == cancelled`` before
    touching the path.
    """
    if upload.status == AgentUploadStatus.cancelled:
        return upload
    if os.path.isfile(upload.stored_path):
        try:
            os.remove(upload.stored_path)
        except OSError:
            # File may already be gone (rotated, manual cleanup); the
            # row update below still proceeds so the user-visible state
            # is consistent.
            pass
    upload.status = AgentUploadStatus.cancelled
    upload.cancelled_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(upload)
    return upload


async def mark_validated(
    db: AsyncSession,
    upload: AgentUpload,
    *,
    detected_document_type: str | None,
    validation_summary: str,
    validation_details: dict,
    accepted: bool,
) -> AgentUpload:
    upload.detected_document_type = detected_document_type
    upload.validation_summary = validation_summary
    upload.validation_details = validation_details
    upload.validated_at = datetime.now(timezone.utc)
    upload.status = (
        AgentUploadStatus.validated if accepted else AgentUploadStatus.rejected
    )
    await db.flush()
    await db.refresh(upload)
    return upload

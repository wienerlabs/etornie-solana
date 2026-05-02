"""export_case tool — generate a case summary in PDF / Word / Excel.

The agent calls this AFTER a filing is recorded so the user gets a
single download link they can hand to their accountant or counsel. The
tool runs the export pipeline server-side, persists the bytes to an
``agent_upload`` row tied to the requesting session, and returns the
upload metadata + a download URL.

Storing the export as an ``agent_upload`` keeps the audit trail in one
place: the user can always pull every artefact attached to a session,
including ones the agent generated.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agent.download_token import make_download_token
from app.agent.models import AgentSession, AgentUpload, AgentUploadStatus
from app.agent.tools.base import Tool, ToolError, register
from app.cases.export import collect_export_context, render_docx, render_pdf, render_xlsx
from app.cases.models import Case
from app.cases.service import get_case
from app.config import settings
from app.database import async_session
from app.users.models import User, UserRole


_FORMATS: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", "pdf"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
}


_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": (
                "UUID of the current agent session (passed in by the "
                "orchestrator runtime context)."
            ),
        },
        "case_number": {
            "type": "string",
            "description": (
                "Public case number in ETR-YYYY-NNNN format (e.g. "
                "ETR-2026-0001). Case-insensitive."
            ),
        },
        "format": {
            "type": "string",
            "enum": ["pdf", "docx", "xlsx"],
            "description": "Export format. Defaults to 'pdf' when omitted.",
        },
    },
    "additionalProperties": False,
    "required": ["session_id", "case_number"],
}


def _can_access(user: User, case: Case) -> bool:
    if user.role == UserRole.admin:
        return True
    if case.client_id is not None and case.client_id == user.id:
        return True
    return False


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    raw_session = args.get("session_id")
    if not isinstance(raw_session, str) or not raw_session.strip():
        raise ToolError("session_id is required and must be a UUID string")
    try:
        session_uuid = uuid.UUID(raw_session)
    except ValueError as exc:
        raise ToolError(f"session_id is not a valid UUID: {exc}") from exc

    raw_case_number = args.get("case_number")
    if not isinstance(raw_case_number, str) or not raw_case_number.strip():
        raise ToolError("case_number is required (e.g. ETR-2026-0001)")

    fmt = (args.get("format") or "pdf").lower()
    if fmt not in _FORMATS:
        raise ToolError(
            f"Unsupported format '{fmt}'. Allowed: pdf, docx, xlsx."
        )
    media_type, ext = _FORMATS[fmt]

    async with async_session() as db:
        session_row = (
            await db.execute(
                select(AgentSession).where(AgentSession.id == session_uuid)
            )
        ).scalar_one_or_none()
        if session_row is None or session_row.deleted_at is not None:
            raise ToolError("session_id does not match an active agent session")

        user_row = (
            await db.execute(
                select(User).where(User.id == session_row.user_id)
            )
        ).scalar_one_or_none()
        if user_row is None:
            raise ToolError("session user no longer exists")

        normalized = raw_case_number.strip().upper()
        from sqlalchemy import func

        case_row = (
            await db.execute(
                select(Case).where(func.upper(Case.case_number) == normalized)
            )
        ).scalar_one_or_none()
        if case_row is None:
            raise ToolError(
                f"No case found with number {raw_case_number.strip()}."
            )
        if not _can_access(user_row, case_row):
            raise ToolError(
                f"Case {case_row.case_number} exists, but you do not have "
                "access to export it."
            )

        case = await get_case(db, case_row.id)
        ctx = await collect_export_context(db, case)
        if fmt == "pdf":
            body = render_pdf(ctx)
        elif fmt == "docx":
            body = render_docx(ctx)
        else:
            body = render_xlsx(ctx)

        target_dir = os.path.join(
            settings.upload_dir, "agent", str(session_uuid)
        )
        os.makedirs(target_dir, exist_ok=True)
        filename = f"etornie-case-{case.case_number}.{ext}"
        stored_filename = f"{uuid.uuid4()}_{filename}"
        stored_path = os.path.join(target_dir, stored_filename)
        with open(stored_path, "wb") as f:
            f.write(body)

        import hashlib

        upload = AgentUpload(
            session_id=session_uuid,
            user_id=user_row.id,
            original_filename=filename,
            stored_path=stored_path,
            mime_type=media_type,
            size_bytes=len(body),
            sha256_hex=hashlib.sha256(body).hexdigest(),
            status=AgentUploadStatus.validated,
            expected_document_type=f"case_export.{ext}",
            detected_document_type=f"case_export.{ext}",
            validation_summary=(
                f"Case {case.case_number} export generated by agent "
                f"({fmt.upper()})."
            ),
            validation_details={
                "format": fmt,
                "case_number": case.case_number,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            validated_at=datetime.now(timezone.utc),
            linked_case_id=case.id,
        )
        db.add(upload)
        await db.flush()
        await db.refresh(upload)

        await db.commit()

    download_token = make_download_token(upload.id)
    public_url = (
        f"{settings.api_public_url.rstrip('/')}"
        f"/agent/uploads/{upload.id}/download?token={download_token}"
    )
    label_by_format = {
        "pdf": "PDF Indir",
        "docx": "Word Indir",
        "xlsx": "Excel Indir",
    }
    link_label = label_by_format[fmt]
    return {
        "case_number": case.case_number,
        "format": fmt,
        "download_url": public_url,
        # Pre-formatted markdown for the agent to relay verbatim. Keeps
        # the user-facing reply to a single tappable link instead of a
        # wall of filename / size / hash detail.
        "markdown_link": f"[{link_label}]({public_url})",
    }


export_case_tool = register(
    Tool(
        name="export_case",
        description=(
            "Generate a branded case summary (PDF, Word, or Excel) and "
            "return a download link. After this tool returns, your reply "
            "to the user MUST be only the value of the `markdown_link` "
            "field — nothing else. Do not restate the filename, size, "
            "hash, or case number; the link itself is the entire answer."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

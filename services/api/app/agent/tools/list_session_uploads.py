"""list_session_uploads tool — what files has the user attached?

Reads the ``agent_upload`` rows for a session and returns a compact view
the model can reason over: id, filename, expected vs detected type,
validation verdict, and ZK ownership state. Cancelled uploads are
omitted so the agent does not propose using a file the user already
discarded.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.agent.tools.base import Tool, ToolError, register
from app.agent.uploads import list_session_uploads
from app.database import async_session


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
    },
    "additionalProperties": False,
    "required": ["session_id"],
}


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    raw_id = args.get("session_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ToolError("session_id is required and must be a UUID string")
    try:
        session_uuid = uuid.UUID(raw_id)
    except ValueError as exc:
        raise ToolError(f"session_id is not a valid UUID: {exc}") from exc

    async with async_session() as db:
        uploads = await list_session_uploads(db, session_id=session_uuid)

    rows: list[dict[str, Any]] = []
    for upload in uploads:
        rows.append(
            {
                "upload_id": str(upload.id),
                "original_filename": upload.original_filename,
                "mime_type": upload.mime_type,
                "size_bytes": upload.size_bytes,
                "status": upload.status.value,
                "expected_document_type": upload.expected_document_type,
                "detected_document_type": upload.detected_document_type,
                "validation_summary": upload.validation_summary,
                "ownership_proof_attached": upload.ownership_verified_at is not None,
                "linked_case_id": (
                    str(upload.linked_case_id) if upload.linked_case_id else None
                ),
                "linked_document_id": (
                    str(upload.linked_document_id)
                    if upload.linked_document_id
                    else None
                ),
                "created_at": upload.created_at.isoformat(),
            }
        )

    return {
        "session_id": str(session_uuid),
        "count": len(rows),
        "uploads": rows,
    }


list_session_uploads_tool = register(
    Tool(
        name="list_session_uploads",
        description=(
            "List every non-cancelled file the user has uploaded inside "
            "the current agent session, with each file's validation "
            "verdict and ZK ownership state. Use this BEFORE asking the "
            "user to upload a file again, and BEFORE filing — so you "
            "know what you already have."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

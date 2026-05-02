"""validate_uploaded_document tool — vision-based intake review.

Given an ``agent_upload`` row id, opens the real file on disk and asks
the Together AI Kimi K2.5 vision endpoint whether the document matches
what the agent asked the user for. The verdict is persisted on the
upload row so subsequent tool calls (and the user-facing chat) stay in
sync.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.agent.models import AgentUpload, AgentUploadStatus
from app.agent.tools.base import Tool, ToolError, register
from app.agent.uploads import get_upload, mark_validated
from app.agent.vision import VisionError, classify_document
from app.database import async_session


_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "upload_id": {
            "type": "string",
            "description": (
                "UUID of an agent_upload row. The file must still be on "
                "disk (not cancelled) and must have been uploaded by the "
                "current session's user."
            ),
        },
        "expected_document_type": {
            "type": "string",
            "description": (
                "Optional override for the document type the agent expects. "
                "When provided, takes precedence over the value recorded "
                "at upload time (e.g. when the user re-uploads against a "
                "different requirement)."
            ),
        },
    },
    "additionalProperties": False,
    "required": ["upload_id"],
}


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    raw_id = args.get("upload_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ToolError("upload_id is required and must be a UUID string")
    try:
        upload_uuid = uuid.UUID(raw_id)
    except ValueError as exc:
        raise ToolError(f"upload_id is not a valid UUID: {exc}") from exc

    expected_override = args.get("expected_document_type")
    if expected_override is not None and not isinstance(expected_override, str):
        raise ToolError("expected_document_type must be a string when supplied")

    async with async_session() as db:
        upload: AgentUpload | None = await get_upload(db, upload_uuid)
        if upload is None:
            raise ToolError(f"No upload found with id {raw_id}.")
        if upload.status == AgentUploadStatus.cancelled:
            raise ToolError(
                f"Upload {raw_id} has been cancelled and is no longer "
                "available for validation."
            )

        expected_type = (
            expected_override.strip()
            if isinstance(expected_override, str) and expected_override.strip()
            else upload.expected_document_type
        )

        try:
            vision_result = await classify_document(
                file_path=upload.stored_path,
                mime_type=upload.mime_type,
                original_filename=upload.original_filename,
                expected_document_type=expected_type,
            )
        except VisionError as exc:
            raise ToolError(f"Vision validation failed: {exc}") from exc

        # Persist the override so future calls surface the right "expected"
        # without the agent having to repeat itself.
        if expected_type and expected_type != upload.expected_document_type:
            upload.expected_document_type = expected_type

        accepted = vision_result.matches_expected and not vision_result.issues
        summary_for_db = vision_result.summary or (
            "Document accepted." if accepted else "Document does not match expectations."
        )
        details_for_db = vision_result.to_dict()
        if expected_type is not None:
            details_for_db["expected_document_type"] = expected_type

        upload = await mark_validated(
            db,
            upload,
            detected_document_type=vision_result.detected_document_type,
            validation_summary=summary_for_db,
            validation_details=details_for_db,
            accepted=accepted,
        )

        await db.commit()

    return {
        "upload_id": str(upload.id),
        "ok": accepted,
        "status": upload.status.value,
        "expected_document_type": expected_type,
        "detected_document_type": vision_result.detected_document_type,
        "matches_expected": vision_result.matches_expected,
        "confidence": vision_result.confidence,
        "summary": vision_result.summary,
        "key_fields": vision_result.key_fields,
        "issues": vision_result.issues,
    }


validate_uploaded_document_tool = register(
    Tool(
        name="validate_uploaded_document",
        description=(
            "Validate a file the user uploaded to the current session by "
            "asking the vision model to identify the document and decide "
            "whether it matches the type the agent asked for. Returns "
            "ok=true only when the detected document genuinely satisfies "
            "the request and there are no blocking issues. Use AFTER the "
            "user uploads a file and BEFORE proceeding to filing."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

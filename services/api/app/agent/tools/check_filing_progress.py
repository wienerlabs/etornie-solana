"""check_filing_progress tool — poll the UK IPO robot's current state.

The Playwright robot writes its `current_step` to the UKIPOSubmission
row after every page transition. The agent calls this tool to surface
that state to the user during the long-running submission.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select

from app.agent.tools.base import Tool, ToolError, register
from app.database import async_session
from app.services.ukipo.models import UKIPOSubmission

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "submission_id": {
            "type": "string",
            "description": "UUID of the UKIPOSubmission row.",
        }
    },
    "additionalProperties": False,
    "required": ["submission_id"],
}


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    try:
        sub_id = uuid.UUID(str(args["submission_id"]))
    except (ValueError, TypeError):
        raise ToolError(f"submission_id is not a valid UUID: {args['submission_id']}")

    async with async_session() as db:
        result = await db.execute(
            select(UKIPOSubmission).where(UKIPOSubmission.id == sub_id)
        )
        submission = result.scalar_one_or_none()
        if submission is None:
            raise ToolError(f"No submission found with id {args['submission_id']}.")

        try:
            nice_classes = json.loads(submission.nice_classes_json)
        except (TypeError, ValueError):
            nice_classes = []

        return {
            "submission_id": str(submission.id),
            "status": submission.status.value,
            "current_step": submission.current_step,
            "error_step": submission.error_step,
            "error_message": submission.error_message,
            "ipo_application_url": submission.ipo_application_url,
            "ipo_reference": submission.ipo_reference,
            "screenshot_path": submission.screenshot_path,
            "owner_company_name": submission.owner_company_name,
            "owner_country": submission.owner_country,
            "mark_text": submission.mark_text,
            "mark_type": submission.mark_type.value,
            "nice_classes": nice_classes,
            "started_at": submission.started_at.isoformat() if submission.started_at else None,
            "finished_at": submission.finished_at.isoformat() if submission.finished_at else None,
        }


check_filing_progress_tool = register(
    Tool(
        name="check_filing_progress",
        description=(
            "Read the current state of a running UK IPO submission. Use "
            "this to report progress to the user while the Playwright "
            "robot is working through the form, and to detect when "
            "status flips to 'awaiting_payment' (robot finished and the "
            "user must now pay) or 'failed' (intervention needed)."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

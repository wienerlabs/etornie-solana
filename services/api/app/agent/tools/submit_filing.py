"""submit_filing tool — submit a case draft to a real IP office.

Thin wrapper around ``app.agent.filing_service``; both this tool and
the Stripe auto-submit path share the same submission logic so the
FilingAttempt audit trail and EUIPO API call live in exactly one
place.

Phase 0 wires only EUIPO. WIPO/USPTO/UKIPO return an explicit
not-wired error (UKIPO ships through the start_ukipo_filing robot
path, not this tool).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.filing_service import (
    FilingServiceError,
    find_submitted_attempt,
    submit_eutm,
)
from app.agent.models import CaseDraft, FilingPlatform
from app.agent.tools.base import Tool, ToolError, register
from app.database import async_session

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "case_draft_id": {
            "type": "string",
            "description": "UUID of the case_draft row to file.",
        },
        "platform": {
            "type": "string",
            "enum": ["EUIPO", "WIPO", "USPTO", "UKIPO"],
            "description": "IP office to submit to.",
        },
    },
    "additionalProperties": False,
    "required": ["case_draft_id", "platform"],
}


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    raw_id = args["case_draft_id"]
    try:
        draft_id = uuid.UUID(raw_id)
    except (ValueError, TypeError):
        raise ToolError(f"case_draft_id is not a valid UUID: {raw_id}")

    platform = args["platform"]
    if platform != "EUIPO":
        raise ToolError(
            f"submit_filing for {platform} is not yet wired in this "
            "milestone. Only EUIPO submissions are supported via this "
            "tool right now (UKIPO ships through the start_ukipo_filing "
            "robot path, not submit_filing)."
        )

    async with async_session() as db:
        draft = (
            await db.execute(
                select(CaseDraft).where(CaseDraft.id == draft_id)
            )
        ).scalar_one_or_none()
        if draft is None:
            raise ToolError(f"No case_draft found with id {raw_id}.")

        # Idempotent: if a previous attempt already succeeded, return
        # that instead of burning another EUIPO API call.
        existing = await find_submitted_attempt(
            db, case_draft_id=draft.id, platform=FilingPlatform.EUIPO
        )
        if existing is not None:
            return {
                "ok": True,
                "platform": "EUIPO",
                "filing_attempt_id": str(existing.id),
                "status": existing.status.value,
                "external_reference": existing.external_reference,
                "already_submitted": True,
            }

        try:
            outcome = await submit_eutm(db, draft, initiated_by="agent_tool")
        except FilingServiceError as exc:
            raise ToolError(str(exc))
        await db.commit()
        return outcome


submit_filing_tool = register(
    Tool(
        name="submit_filing",
        description=(
            "Submit a paid case_draft to the chosen IP office. EUIPO is "
            "the only wired adapter today. Returns the filing_attempt "
            "id and the external reference (EUIPO application number) "
            "on success. UKIPO submissions ship through start_ukipo_filing."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

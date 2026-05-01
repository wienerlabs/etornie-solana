"""create_case_draft tool — persist or update the user's slot-filling state.

Once the agent has collected enough fields (mark text, applicant, Nice
classes, target countries) it calls this tool to write a row into
case_draft. A session has at most one draft (1:1), so a second call for
the same session updates the existing row.

This is the bridge between the chat-only Phase 0 and the real DB-backed
filing flow that follows.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.models import (
    ApplicantType,
    CaseDraft,
    CaseDraftStatus,
)
from app.agent.tools.base import Tool, ToolError, register
from app.cases.models import CaseType
from app.database import async_session

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": (
                "UUID of the agent_session this draft belongs to. Use the "
                "exact session_id from the runtime context."
            ),
        },
        "user_id": {
            "type": "string",
            "description": (
                "UUID of the authenticated user. Use the exact user_id "
                "from the runtime context."
            ),
        },
        "case_type": {
            "type": "string",
            "enum": ["trademark", "patent", "design", "copyright"],
        },
        "mark_text": {
            "type": "string",
            "description": "The trademark text being registered.",
        },
        "applicant_name": {"type": "string"},
        "applicant_type": {
            "type": "string",
            "enum": ["individual", "legal_entity"],
        },
        "target_countries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "ISO codes or country names.",
        },
        "selected_platforms": {
            "type": "array",
            "items": {"type": "string", "enum": ["EUIPO", "WIPO", "USPTO", "UKIPO"]},
        },
        "nice_classes": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "logo_file_id": {
            "type": "string",
            "description": "UUID of an uploaded logo file, if any.",
        },
    },
    "additionalProperties": False,
    "required": [
        "session_id",
        "user_id",
        "case_type",
        "mark_text",
        "applicant_name",
        "applicant_type",
        "target_countries",
        "selected_platforms",
        "nice_classes",
    ],
}


def _parse_uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise ToolError(f"{field} is not a valid UUID: {value}")


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    session_id = _parse_uuid(args["session_id"], "session_id")
    user_id = _parse_uuid(args["user_id"], "user_id")

    nice_classes = list(args["nice_classes"])
    if not nice_classes:
        raise ToolError("nice_classes must contain at least one entry.")
    if any(c < 1 or c > 45 for c in nice_classes):
        raise ToolError(f"Nice classes must be in 1-45 (got {nice_classes}).")

    try:
        case_type = CaseType(args["case_type"])
    except ValueError:
        raise ToolError(f"Unknown case_type: {args['case_type']}")
    try:
        applicant_type = ApplicantType(args["applicant_type"])
    except ValueError:
        raise ToolError(f"Unknown applicant_type: {args['applicant_type']}")

    target_countries = [str(c) for c in args["target_countries"]]
    selected_platforms = [str(p) for p in args["selected_platforms"]]
    if not target_countries:
        raise ToolError("target_countries cannot be empty.")
    if not selected_platforms:
        raise ToolError("selected_platforms cannot be empty.")

    logo_file_id_raw = args.get("logo_file_id")
    logo_file_id = (
        _parse_uuid(logo_file_id_raw, "logo_file_id")
        if logo_file_id_raw
        else None
    )

    async with async_session() as db:
        result = await db.execute(
            select(CaseDraft).where(CaseDraft.session_id == session_id)
        )
        draft = result.scalar_one_or_none()

        if draft is None:
            draft = CaseDraft(
                session_id=session_id,
                user_id=user_id,
                case_type=case_type,
                mark_text=args["mark_text"],
                applicant_name=args["applicant_name"],
                applicant_type=applicant_type,
                target_countries=target_countries,
                selected_platforms=selected_platforms,
                nice_classes=nice_classes,
                logo_file_id=logo_file_id,
                status=CaseDraftStatus.collecting,
            )
            db.add(draft)
        else:
            if draft.user_id != user_id:
                raise ToolError(
                    "The draft attached to this session belongs to a "
                    "different user."
                )
            draft.case_type = case_type
            draft.mark_text = args["mark_text"]
            draft.applicant_name = args["applicant_name"]
            draft.applicant_type = applicant_type
            draft.target_countries = target_countries
            draft.selected_platforms = selected_platforms
            draft.nice_classes = nice_classes
            draft.logo_file_id = logo_file_id

        # Promote to 'validated' once every required slot is filled.
        # logo is optional; everything else is required.
        if all(
            [
                draft.mark_text,
                draft.applicant_name,
                draft.applicant_type,
                draft.target_countries,
                draft.selected_platforms,
                draft.nice_classes,
            ]
        ):
            draft.status = CaseDraftStatus.validated

        await db.commit()
        await db.refresh(draft)

        return {
            "case_draft_id": str(draft.id),
            "session_id": str(draft.session_id),
            "status": draft.status.value,
            "mark_text": draft.mark_text,
            "applicant_name": draft.applicant_name,
            "applicant_type": draft.applicant_type.value,
            "target_countries": draft.target_countries,
            "selected_platforms": draft.selected_platforms,
            "nice_classes": draft.nice_classes,
            "logo_file_id": str(draft.logo_file_id) if draft.logo_file_id else None,
        }


create_case_draft_tool = register(
    Tool(
        name="create_case_draft",
        description=(
            "Persist or update the user's filing draft once you have all "
            "required slots: mark text, applicant name, applicant type, "
            "target countries, selected platforms, and Nice classes. "
            "Returns the case_draft_id you must pass to prepare_payment "
            "and submit_filing later."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

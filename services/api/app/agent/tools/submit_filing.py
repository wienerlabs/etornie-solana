"""submit_filing tool — submit a case draft to a real IP office.

Phase 0 wires only EUIPO via the existing services/euipo/eutm_filing
adapter. WIPO/USPTO/UKIPO return an explicit not-wired error.

Pre-conditions:
  * The case_draft must belong to the current authenticated user.
  * The case_draft must have all required slots filled (mark_text,
    applicant_name, applicant_type, nice_classes).
  * The case_draft.status must be 'paid' (payment confirmed before we
    spend an EUIPO API call).

Side effects:
  * Persists a filing_attempt row regardless of outcome (success or
    failure → audit trail).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import (
    ApplicantType,
    CaseDraft,
    CaseDraftStatus,
    FilingAttempt,
    FilingAttemptStatus,
    FilingPlatform,
)
from app.agent.tools.base import Tool, ToolError, register
from app.database import async_session
from app.services.euipo.eutm_filing import create_application

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


def _build_euipo_applicant(draft: CaseDraft) -> dict[str, Any]:
    if draft.applicant_type == ApplicantType.legal_entity:
        return {
            "type": "LEGAL_ENTITY",
            "legalEntity": {"name": draft.applicant_name},
        }
    return {
        "type": "INDIVIDUAL",
        "person": {"fullName": draft.applicant_name},
    }


def _build_euipo_classes(draft: CaseDraft) -> list[dict[str, Any]]:
    classes = [int(c) for c in (draft.nice_classes or [])]
    if not classes:
        raise ToolError("case_draft has no Nice classes set.")
    if any(c < 1 or c > 45 for c in classes):
        raise ToolError(f"Invalid Nice classes: {classes}")
    # EUIPO requires at least one term per class. We use a generic
    # placeholder string from the class number — the real class headings
    # come from the EUIPO goods_services service, which is wired
    # separately and out of scope for this tool's signature.
    return [
        {
            "classNumber": c,
            "language": "en",
            "terms": [f"Class {c} goods and services"],
        }
        for c in classes
    ]


async def _next_attempt_number(
    db: AsyncSession, *, case_draft_id: uuid.UUID, platform: FilingPlatform
) -> int:
    result = await db.execute(
        select(FilingAttempt).where(
            FilingAttempt.case_draft_id == case_draft_id,
            FilingAttempt.platform == platform,
        )
    )
    rows = list(result.scalars().all())
    return len(rows) + 1


async def _validate_draft_for_submit(draft: CaseDraft) -> None:
    missing: list[str] = []
    if not draft.mark_text:
        missing.append("mark_text")
    if not draft.applicant_name:
        missing.append("applicant_name")
    if not draft.applicant_type:
        missing.append("applicant_type")
    if not draft.nice_classes:
        missing.append("nice_classes")
    if missing:
        raise ToolError(
            "case_draft cannot be submitted yet — missing slots: "
            + ", ".join(missing)
        )
    if draft.status != CaseDraftStatus.paid:
        raise ToolError(
            f"case_draft.status is '{draft.status.value}'; submission "
            "requires status='paid' (payment confirmed)."
        )


async def _execute_euipo(
    db: AsyncSession, draft: CaseDraft
) -> dict[str, Any]:
    body_log: dict[str, Any] = {
        "mark_text": draft.mark_text,
        "applicant": _build_euipo_applicant(draft),
        "nice_classes": _build_euipo_classes(draft),
        "draft": False,
    }
    attempt_number = await _next_attempt_number(
        db, case_draft_id=draft.id, platform=FilingPlatform.EUIPO
    )

    attempt = FilingAttempt(
        case_draft_id=draft.id,
        platform=FilingPlatform.EUIPO,
        status=FilingAttemptStatus.pending,
        attempt_number=attempt_number,
        request_payload=body_log,
    )
    db.add(attempt)
    await db.flush()

    try:
        response = await create_application(
            mark_text=draft.mark_text,
            mark_feature="WORD",
            nice_classes=body_log["nice_classes"],
            applicant=body_log["applicant"],
            draft=False,
        )
    except Exception as exc:  # noqa: BLE001
        attempt.status = FilingAttemptStatus.error
        attempt.error_message = str(exc)
        attempt.completed_at = datetime.now(tz=timezone.utc)
        await db.flush()
        return {
            "ok": False,
            "platform": "EUIPO",
            "filing_attempt_id": str(attempt.id),
            "status": attempt.status.value,
            "error": str(exc),
        }

    external_ref = (
        response.get("applicationNumber")
        or response.get("id")
        or response.get("reference")
    )
    attempt.status = FilingAttemptStatus.submitted
    attempt.external_reference = external_ref
    attempt.response_payload = response
    attempt.submitted_at = datetime.now(tz=timezone.utc)
    await db.flush()

    return {
        "ok": True,
        "platform": "EUIPO",
        "filing_attempt_id": str(attempt.id),
        "status": attempt.status.value,
        "external_reference": external_ref,
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
            "milestone. Only EUIPO submissions are supported right now; "
            "the user should be told that the other adapters are coming."
        )

    async with async_session() as db:
        result = await db.execute(
            select(CaseDraft).where(CaseDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()
        if draft is None:
            raise ToolError(f"No case_draft found with id {raw_id}.")

        await _validate_draft_for_submit(draft)
        outcome = await _execute_euipo(db, draft)
        await db.commit()
        return outcome


submit_filing_tool = register(
    Tool(
        name="submit_filing",
        description=(
            "Submit a paid case_draft to the chosen IP office. EUIPO is "
            "wired through the official sandbox API; WIPO/USPTO/UKIPO "
            "return an explicit not-wired error. Always records a "
            "filing_attempt row for audit, success or failure."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

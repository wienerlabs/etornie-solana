"""start_ukipo_filing tool — kick off the existing UK IPO Playwright robot.

Reuses the production-grade robot in `services/ukipo` exactly as it is.
The agent collects owner address, entity type, and Nice class descriptions
through conversation, then calls this tool. The tool:

  1. Promotes the case_draft into the legacy `cases` table (the UK IPO
     submission row needs a case_id FK).
  2. Creates a UKIPOSubmission row with the owner snapshot.
  3. Starts the Playwright robot in the background.
  4. Returns immediately with the submission_id so the agent can tell
     the user the robot is working and the frontend can poll progress.

Etornie's own representative + declarant details are read from settings
(UKIPO_REP_*, UKIPO_DECLARANT_NAME) — those env vars must be set.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.models import (
    CaseDraft,
    CaseDraftStatus,
)
from app.agent.tools.base import Tool, ToolError, register
from app.cases.models import Case, CaseStatus, CaseType as DomainCaseType
from app.cases.service import create_case
from app.database import async_session
from app.services.ukipo.models import (
    UKIPOMarkType,
    UKIPOOwnerEntityType,
    UKIPOSubmissionStatus,
)
from app.services.ukipo.service import create_submission, start_submission_run


_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "case_draft_id": {
            "type": "string",
            "description": "UUID of the validated case_draft.",
        },
        "owner_country": {
            "type": "string",
            "description": "Owner country (full English name, e.g. 'United Kingdom', 'Turkey').",
        },
        "owner_address_line1": {"type": "string"},
        "owner_address_line2": {"type": "string"},
        "owner_city": {"type": "string"},
        "owner_postcode": {
            "type": "string",
            "description": "Required when owner_country is in the UK.",
        },
        "owner_email": {"type": "string"},
        "owner_phone": {"type": "string"},
        "owner_entity_type": {
            "type": "string",
            "enum": [
                "Registered Company or LLP",
                "Individual(s)",
                "Partnership",
                "Trust",
                "Other",
            ],
            "description": "UK IPO owner entity type label.",
        },
        "owner_company_registration_number": {
            "type": "string",
            "description": (
                "Required when owner_country is in the UK and "
                "owner_entity_type is 'Registered Company or LLP'."
            ),
        },
        "mark_type": {
            "type": "string",
            "enum": ["word", "figurative", "combined", "unusual"],
        },
        "mark_image_path": {
            "type": "string",
            "description": (
                "Local file path of the logo, required for figurative / "
                "combined / unusual marks."
            ),
        },
        "nice_class_descriptions": {
            "type": "array",
            "description": (
                "One entry per Nice class on the draft. UK IPO needs a "
                "human-readable description per class (e.g. 'Computer "
                "software for AI-driven analytics')."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "class_number": {"type": "integer"},
                    "description": {"type": "string"},
                },
                "additionalProperties": False,
                "required": ["class_number", "description"],
            },
        },
    },
    "additionalProperties": False,
    "required": [
        "case_draft_id",
        "owner_country",
        "owner_address_line1",
        "owner_city",
        "owner_entity_type",
        "mark_type",
        "nice_class_descriptions",
    ],
}


def _parse_uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise ToolError(f"{field} is not a valid UUID: {value}")


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    draft_id = _parse_uuid(args["case_draft_id"], "case_draft_id")
    mark_type = UKIPOMarkType(args["mark_type"])

    try:
        owner_entity_type = UKIPOOwnerEntityType(args["owner_entity_type"])
    except ValueError:
        raise ToolError(
            f"Unknown owner_entity_type: {args['owner_entity_type']}"
        )

    nice_descriptions = args["nice_class_descriptions"]
    if not nice_descriptions:
        raise ToolError("nice_class_descriptions cannot be empty.")

    async with async_session() as db:
        result = await db.execute(
            select(CaseDraft).where(CaseDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()
        if draft is None:
            raise ToolError(f"No case_draft found with id {args['case_draft_id']}.")

        if draft.status not in (
            CaseDraftStatus.validated,
            CaseDraftStatus.awaiting_payment,
            CaseDraftStatus.paid,
        ):
            raise ToolError(
                f"case_draft.status is '{draft.status.value}'; the robot "
                "can only start from a validated draft."
            )
        if not draft.mark_text:
            raise ToolError("case_draft.mark_text is missing.")
        if not draft.applicant_name:
            raise ToolError("case_draft.applicant_name is missing.")

        # Cross-check that every draft Nice class has a description.
        draft_classes = sorted(int(c) for c in (draft.nice_classes or []))
        provided_classes = sorted(int(d["class_number"]) for d in nice_descriptions)
        if draft_classes != provided_classes:
            raise ToolError(
                "nice_class_descriptions must cover exactly the draft's "
                f"Nice classes. Draft has {draft_classes}, got "
                f"{provided_classes}."
            )

        # 1. Promote the draft into the legacy `cases` table so we have a
        #    case_id to satisfy UKIPOSubmission.case_id FK. We use status
        #    'open' — the case lifecycle is independent from the
        #    submission lifecycle.
        if draft.promoted_case_id is None:
            case = await create_case(
                db,
                title=draft.mark_text,
                description=(
                    f"UK IPO trademark filing initiated by EtornieGPT "
                    f"agent for {draft.applicant_name}"
                ),
                case_type=DomainCaseType.trademark.value,
                client_id=draft.user_id,
                jurisdiction="United Kingdom",
                nice_classes=",".join(str(c) for c in draft_classes),
            )
            await db.flush()
            draft.promoted_case_id = case.id
            await db.flush()
        else:
            case_lookup = await db.execute(
                select(Case).where(Case.id == draft.promoted_case_id)
            )
            case = case_lookup.scalar_one()

        # 2. Create the UK IPO submission snapshot.
        nice_classes_payload = [
            {
                "class_number": int(d["class_number"]),
                "description": str(d["description"]),
            }
            for d in nice_descriptions
        ]

        try:
            submission = await create_submission(
                db,
                case_id=case.id,
                owner_company_name=draft.applicant_name,
                owner_country=args["owner_country"],
                owner_address_line1=args["owner_address_line1"],
                owner_address_line2=args.get("owner_address_line2"),
                owner_city=args["owner_city"],
                owner_postcode=args.get("owner_postcode"),
                owner_email=args.get("owner_email"),
                owner_phone=args.get("owner_phone"),
                owner_entity_type=owner_entity_type,
                owner_company_registration_number=args.get(
                    "owner_company_registration_number"
                ),
                mark_type=mark_type,
                mark_text=draft.mark_text,
                mark_image_path=args.get("mark_image_path"),
                nice_classes=nice_classes_payload,
            )
        except ValueError as exc:
            raise ToolError(str(exc))

        await db.commit()
        submission_id = submission.id

    # 3. Kick off the robot in a fresh DB session — start_submission_run
    #    re-fetches the row and owns the background task lifecycle.
    async with async_session() as db:
        result = await db.execute(
            select(__import__(
                "app.services.ukipo.models", fromlist=["UKIPOSubmission"]
            ).UKIPOSubmission).where(
                __import__(
                    "app.services.ukipo.models", fromlist=["UKIPOSubmission"]
                ).UKIPOSubmission.id == submission_id
            )
        )
        submission = result.scalar_one()

        try:
            submission = await start_submission_run(db, submission)
        except RuntimeError as exc:
            raise ToolError(f"Could not start UK IPO robot: {exc}")

        await db.commit()

        return {
            "submission_id": str(submission.id),
            "case_id": str(submission.case_id),
            "status": submission.status.value,
            "current_step": submission.current_step,
            "owner_company_name": submission.owner_company_name,
            "owner_country": submission.owner_country,
            "mark_text": submission.mark_text,
            "mark_type": submission.mark_type.value,
            "nice_classes": nice_classes_payload,
            "user_action_required": (
                "The Playwright robot has started filling out the UK IPO "
                "application. Tell the user to wait while the robot works "
                "through each step. Use check_filing_progress periodically "
                "to report current_step. The robot will stop on the "
                "declaration page and switch to status='awaiting_payment' "
                "— at that point, the user must complete the wallet "
                "payment to authorize the £265 GBP fee."
            ),
        }


start_ukipo_filing_tool = register(
    Tool(
        name="start_ukipo_filing",
        description=(
            "Start the UK IPO Playwright robot for a validated case_draft "
            "(jurisdiction must be UK). Promotes the draft into a Case "
            "row, creates a UKIPOSubmission, and triggers the robot in "
            "the background. Returns immediately with submission_id; use "
            "check_filing_progress to poll status and current_step."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

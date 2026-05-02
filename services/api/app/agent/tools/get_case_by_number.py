"""get_case_by_number tool — fetch a case by its public ETR-YYYY-NNNN id.

Used when the user references one of their existing cases ("ETR-2026-0001
ne durumda?"). The tool resolves the session's authenticated user from
the agent_session row, looks up the case, and refuses to return data
unless the user is the case's client or its assigned lawyer (or admin).

Output is a flat read-only summary the LLM can paraphrase: case fields,
on-chain attestation + NFT state, latest UKIPO submission progress (if
any), the count and status mix of uploaded documents, and any pending
required documents.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import AgentSession
from app.agent.tools.base import Tool, ToolError, register
from app.cases.models import Case
from app.database import async_session
from app.documents.models import Document, DocumentStatus
from app.required_documents.models import CaseRequiredDocument
from app.services.ukipo.models import UKIPOSubmission
from app.users.models import User, UserRole


_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "case_number": {
            "type": "string",
            "description": (
                "Public case number in ETR-YYYY-NNNN format (e.g. "
                "ETR-2026-0001). Case-insensitive."
            ),
        },
        "session_id": {
            "type": "string",
            "description": (
                "UUID of the current agent session (passed in by the "
                "orchestrator runtime context). The tool uses this to "
                "look up the authenticated user and authorize access."
            ),
        },
    },
    "additionalProperties": False,
    "required": ["case_number", "session_id"],
}


def _can_access(user: User, case: Case) -> bool:
    if user.role == UserRole.admin:
        return True
    if case.client_id is not None and case.client_id == user.id:
        return True
    return False


async def _load_session_user(
    db: AsyncSession, session_id: uuid.UUID
) -> User:
    result = await db.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None or session.deleted_at is not None:
        raise ToolError("session_id does not match an active agent session")
    user_result = await db.execute(
        select(User).where(User.id == session.user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise ToolError("session user no longer exists")
    return user


async def _load_case(db: AsyncSession, case_number: str) -> Case | None:
    normalized = case_number.strip().upper()
    result = await db.execute(
        select(Case).where(func.upper(Case.case_number) == normalized)
    )
    return result.scalar_one_or_none()


async def _summarize_documents(
    db: AsyncSession, case_id: uuid.UUID
) -> dict[str, Any]:
    docs_result = await db.execute(
        select(Document).where(Document.case_id == case_id)
    )
    documents = list(docs_result.scalars().all())
    by_status: dict[str, int] = {}
    for doc in documents:
        key = doc.status.value
        by_status[key] = by_status.get(key, 0) + 1
    ownership_verified = sum(
        1 for d in documents if d.ownership_verified_at is not None
    )

    req_result = await db.execute(
        select(CaseRequiredDocument).where(
            CaseRequiredDocument.case_id == case_id
        )
    )
    required = list(req_result.scalars().all())
    pending = [r.document_name for r in required if r.status == DocumentStatus.pending]

    return {
        "total": len(documents),
        "by_status": by_status,
        "ownership_proofs_verified": ownership_verified,
        "pending_required": pending,
    }


async def _latest_ukipo_submission(
    db: AsyncSession, case_id: uuid.UUID
) -> dict[str, Any] | None:
    result = await db.execute(
        select(UKIPOSubmission)
        .where(UKIPOSubmission.case_id == case_id)
        .order_by(UKIPOSubmission.created_at.desc())
        .limit(1)
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        return None
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
        "mark_text": submission.mark_text,
        "nice_classes": nice_classes,
        "payment_tx": submission.solana_payment_tx,
        "payment_lamports": submission.solana_payment_lamports,
        "payment_at": (
            submission.solana_payment_at.isoformat()
            if submission.solana_payment_at
            else None
        ),
        "started_at": (
            submission.started_at.isoformat() if submission.started_at else None
        ),
        "finished_at": (
            submission.finished_at.isoformat() if submission.finished_at else None
        ),
    }


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    raw_number = args.get("case_number")
    if not isinstance(raw_number, str) or not raw_number.strip():
        raise ToolError("case_number is required (e.g. ETR-2026-0001)")

    raw_session = args.get("session_id")
    if not isinstance(raw_session, str) or not raw_session.strip():
        raise ToolError("session_id is required and must be a UUID string")
    try:
        session_uuid = uuid.UUID(raw_session)
    except ValueError as exc:
        raise ToolError(f"session_id is not a valid UUID: {exc}") from exc

    async with async_session() as db:
        user = await _load_session_user(db, session_uuid)
        case = await _load_case(db, raw_number)
        if case is None:
            raise ToolError(
                f"No case found with number {raw_number.strip()}. "
                "Numbers follow ETR-YYYY-NNNN."
            )
        if not _can_access(user, case):
            raise ToolError(
                f"Case {case.case_number} exists, but you do not have access to it. "
                "Only the client, the assigned lawyer, or an admin can view it."
            )

        documents_summary = await _summarize_documents(db, case.id)
        ukipo_summary = await _latest_ukipo_submission(db, case.id)

        nice_classes_list: list[int] = []
        if case.nice_classes:
            for token in case.nice_classes.split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    nice_classes_list.append(int(token))
                except ValueError:
                    continue

        return {
            "case_number": case.case_number,
            "case_id": str(case.id),
            "title": case.title,
            "description": case.description,
            "case_type": case.case_type.value,
            "status": case.status.value,
            "jurisdiction": case.jurisdiction,
            "nice_classes": nice_classes_list,
            "filing_date": case.filing_date.isoformat() if case.filing_date else None,
            "deadline": case.deadline.isoformat() if case.deadline else None,
            "client_wallet": case.client_wallet,
            "attestation_tx": case.attestation_tx,
            "attestation_pda": case.attestation_pda,
            "nft": {
                "state": case.nft_state.value,
                "mint": case.nft_mint,
                "setup_tx": case.nft_setup_tx,
                "mint_tx": case.nft_mint_tx,
                "burn_tx": case.nft_burn_tx,
                "burned_at": (
                    case.nft_burned_at.isoformat() if case.nft_burned_at else None
                ),
            },
            "documents": documents_summary,
            "latest_ukipo_submission": ukipo_summary,
            "created_at": case.created_at.isoformat(),
            "updated_at": case.updated_at.isoformat(),
        }


get_case_by_number_tool = register(
    Tool(
        name="get_case_by_number",
        description=(
            "Look up an existing case by its public ETR-YYYY-NNNN number "
            "and return a read-only summary: type, status, jurisdiction, "
            "Nice classes, on-chain attestation + NFT state, latest "
            "filing-robot progress, and a count of uploaded documents. "
            "Access is gated to the case's client, assigned lawyer, or "
            "an admin. Use whenever the user references a case number."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

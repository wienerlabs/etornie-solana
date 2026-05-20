"""Reusable submission service shared by tools and payment hooks.

Both the agent's ``submit_filing`` tool and the post-Stripe-confirm
auto-trigger call into here, so the EUIPO API call lives in exactly
one place and the FilingAttempt audit trail looks identical regardless
of who initiated the submission.

Side effects: persists a ``FilingAttempt`` row (status=submitted on
success, status=error on failure) and returns a structured result.
Callers are responsible for committing the surrounding transaction.
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
from app.services.euipo.eutm_filing import create_application


class FilingServiceError(RuntimeError):
    """Pre-flight check failed (missing draft fields, wrong status, etc).

    The EUIPO API itself returning an error does NOT raise — that is
    captured on the persisted FilingAttempt row so the audit trail is
    complete.
    """


def _build_euipo_applicant(draft: CaseDraft) -> dict[str, Any]:
    """Shape an applicant payload that matches the EUIPO sandbox schema.

    EUIPO expects ``type`` ∈ {APPLICANT_BUSINESS, APPLICANT_INDIVIDUAL,
    REFERENCE} — REFERENCE is for re-using an existing applicant
    record from the operator's portfolio (out of scope here). The
    ``LEGAL_ENTITY`` / ``INDIVIDUAL`` strings used by older revisions
    of this code were rejected with a 400 validation error from
    /applications.
    """
    if draft.applicant_type == ApplicantType.legal_entity:
        return {
            "type": "APPLICANT_BUSINESS",
            "legalEntity": {"name": draft.applicant_name},
        }
    return {
        "type": "APPLICANT_INDIVIDUAL",
        "person": {"fullName": draft.applicant_name},
    }


def _build_euipo_classes(draft: CaseDraft) -> list[dict[str, Any]]:
    classes = [int(c) for c in (draft.nice_classes or [])]
    if not classes:
        raise FilingServiceError("case_draft has no Nice classes set.")
    if any(c < 1 or c > 45 for c in classes):
        raise FilingServiceError(f"Invalid Nice classes: {classes}")
    # EUIPO requires at least one term per class. The class headings
    # come from services.euipo.goods_services in the real flow; for
    # the initial submission we send a generic placeholder so the
    # application is accepted in sandbox.
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
    return len(list(result.scalars().all())) + 1


async def find_submitted_attempt(
    db: AsyncSession, *, case_draft_id: uuid.UUID, platform: FilingPlatform
) -> FilingAttempt | None:
    """Return a successful FilingAttempt for this draft, if any.

    Used by the Stripe auto-trigger to short-circuit when a previous
    submission already landed — never spend another EUIPO API call on
    an already-filed draft.
    """
    result = await db.execute(
        select(FilingAttempt).where(
            FilingAttempt.case_draft_id == case_draft_id,
            FilingAttempt.platform == platform,
            FilingAttempt.status.in_(
                (FilingAttemptStatus.submitted, FilingAttemptStatus.accepted)
            ),
        )
    )
    return result.scalars().first()


def assert_submittable(draft: CaseDraft) -> None:
    """Raise FilingServiceError if the draft is not ready to ship to EUIPO."""
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
        raise FilingServiceError(
            "case_draft cannot be submitted yet — missing slots: "
            + ", ".join(missing)
        )
    if draft.status != CaseDraftStatus.paid:
        raise FilingServiceError(
            f"case_draft.status is '{draft.status.value}'; submission "
            "requires status='paid' (payment confirmed)."
        )


def _build_euipo_signatures(draft: CaseDraft) -> list[dict[str, Any]]:
    """Minimum signature payload EUIPO accepts on /applications.

    Sandbox rejects the request with ``"signatures: must not be
    empty"`` when this is missing. We sign as the applicant in the
    capacity that matches their type — production filings will need
    explicit consent capture from a real authorised signatory.
    """
    # EUIPO sandbox accepts: APPLICANT, EMPLOYEE_REPRESENTATIVE,
    # LEGAL_PRACTITIONER, PROFESSIONAL_PRACTITIONER. Self-filing
    # (no agent) is captured under APPLICANT for both legal entities
    # and individuals.
    return [
        {
            "signature": draft.applicant_name,
            "capacity": "APPLICANT",
        }
    ]


async def submit_eutm(
    db: AsyncSession,
    draft: CaseDraft,
    *,
    initiated_by: str,
) -> dict[str, Any]:
    """Submit a paid case_draft to EUIPO and persist the attempt.

    ``initiated_by`` is a free-text source label ("agent_tool",
    "stripe_auto") that lands on FilingAttempt.request_payload so the
    audit trail records which path triggered the call.
    """
    assert_submittable(draft)

    nice_classes = _build_euipo_classes(draft)
    applicant = _build_euipo_applicant(draft)
    signatures = _build_euipo_signatures(draft)

    request_payload: dict[str, Any] = {
        "mark_text": draft.mark_text,
        "applicant": applicant,
        "nice_classes": nice_classes,
        "signatures": signatures,
        "draft": False,
        "initiated_by": initiated_by,
    }

    attempt_number = await _next_attempt_number(
        db, case_draft_id=draft.id, platform=FilingPlatform.EUIPO
    )
    attempt = FilingAttempt(
        case_draft_id=draft.id,
        platform=FilingPlatform.EUIPO,
        status=FilingAttemptStatus.pending,
        attempt_number=attempt_number,
        request_payload=request_payload,
    )
    db.add(attempt)
    await db.flush()

    try:
        response = await create_application(
            mark_text=draft.mark_text,
            mark_feature="WORD",
            nice_classes=nice_classes,
            applicant=applicant,
            signatures=signatures,
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

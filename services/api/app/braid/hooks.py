"""Fire-and-forget BRAID hooks for backend domain flows.

Each hook is a coroutine that:

* Decides whether the trigger applies (case is a trademark, has Nice
  classes, ...). If not, returns silently.
* Calls the relevant BRAID capability via :mod:`app.braid.internal`.
* Catches every exception. The hook MUST NOT propagate failure: the
  domain operation (case create, proposal generate, UK IPO submission)
  has already succeeded by the time we run, and a flaky LLM call
  must not block the user-visible flow. All audit / failure context
  goes to ``logger.warning`` and the BraidDecision audit row.

The hook tags every audit row with a ``user_message`` of
``case:<case_id>`` (or ``submission:<id>``) so the dashboard / inline
panels can filter decisions back to the originating record.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.braid.internal import BraidCapabilityError, call_capability
from app.cases.models import Case, CaseType
from app.config import settings

logger = logging.getLogger(__name__)


def _is_braid_enabled() -> bool:
    """BRAID is opt-in; without an internal token the hooks no-op."""
    return bool(settings.braid_internal_token.strip())


def _parse_nice_classes(raw: str | None) -> list[int]:
    """Parse a case.nice_classes string ("25,35,41") into ints 1..45."""
    if not raw:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            continue
        if 1 <= n <= 45 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _case_user_message(case_id: uuid.UUID) -> str:
    return f"case:{case_id}"


def _submission_user_message(submission_id: uuid.UUID) -> str:
    return f"submission:{submission_id}"


async def validate_nice_for_case(db: AsyncSession, case: Case) -> None:
    """Validate the case's Nice class list against its mark description.

    No-op for non-trademark cases or cases without Nice classes /
    description text. Result is recorded in BraidDecision audit; the
    UI surfaces it on the case detail page.
    """
    if not _is_braid_enabled():
        return
    if case.case_type != CaseType.trademark:
        return
    proposed = _parse_nice_classes(case.nice_classes)
    if not proposed:
        return
    mark_description = (case.description or case.title or "").strip()
    if len(mark_description) < 3:
        return

    try:
        from app.braid.router import (
            ValidateNiceClassificationRequest,
            validate_nice_classification,
        )

        request = ValidateNiceClassificationRequest(
            mark_description=mark_description,
            proposed_classes=proposed,
            mark_name=case.title,
        )
        await call_capability(
            db,
            capability_name="validate_nice_classification",
            request=request,
            handler=validate_nice_classification,
            user_message=_case_user_message(case.id),
        )
    except BraidCapabilityError as exc:
        logger.warning(
            "braid: nice-validation declined for case %s (status=%s): %s",
            case.id,
            exc.status_code,
            exc,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "braid: nice-validation hook crashed for case %s", case.id
        )


async def score_completeness_for_case(
    db: AsyncSession,
    case: Case,
) -> None:
    """Score the case's required-document checklist completeness.

    Lets the lawyer know — at proposal generation time — whether the
    client has uploaded enough to actually file. The capability does
    its own DB lookup of the case_required_documents rows.
    """
    if not _is_braid_enabled():
        return

    try:
        from app.braid.router import (
            ScoreDocumentCompletenessRequest,
            score_document_completeness,
        )

        request = ScoreDocumentCompletenessRequest(case_id=case.id)
        await call_capability(
            db,
            capability_name="score_document_completeness",
            request=request,
            handler=score_document_completeness,
            handler_kwargs={"db": db},
            user_message=_case_user_message(case.id),
        )
    except BraidCapabilityError as exc:
        logger.warning(
            "braid: completeness scoring declined for case %s (status=%s): %s",
            case.id,
            exc.status_code,
            exc,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "braid: completeness hook crashed for case %s", case.id
        )


async def check_conflict_for_filing(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    case_id: uuid.UUID,
    mark_text: str,
    nice_classes: list[int],
    jurisdiction: str,
) -> None:
    """Run a trademark conflict check before a real filing kicks off.

    ``jurisdiction`` must be one of the offices the BRAID capability
    knows how to search ({"eu", "uk", "au", "wipo"}); anything else is
    skipped silently. The result is audited but not blocking — the
    operator sees the risk badge in the panel and decides whether to
    proceed.
    """
    if not _is_braid_enabled():
        return
    if not mark_text.strip() or not nice_classes:
        return
    jurisdiction = jurisdiction.strip().lower()
    if jurisdiction not in {"eu", "uk", "au", "wipo"}:
        return

    try:
        from app.braid.router import (
            CheckTrademarkConflictRequest,
            check_trademark_conflict,
        )

        request = CheckTrademarkConflictRequest(
            mark_text=mark_text,
            nice_classes=nice_classes,
            jurisdiction=jurisdiction,  # type: ignore[arg-type]
        )
        await call_capability(
            db,
            capability_name="check_trademark_conflict",
            request=request,
            handler=check_trademark_conflict,
            user_message=(
                f"{_case_user_message(case_id)} "
                f"{_submission_user_message(submission_id)}"
            ),
        )
    except BraidCapabilityError as exc:
        logger.warning(
            "braid: conflict check declined for submission %s (status=%s): %s",
            submission_id,
            exc.status_code,
            exc,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "braid: conflict hook crashed for submission %s", submission_id
        )

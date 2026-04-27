"""Tests for BRAID hook integration into domain flows.

Each hook is fire-and-forget — failure must never propagate. We test:

* skip path: hook returns silently when input doesn't qualify
* enabled path: hook calls the capability handler (mocked) and writes
  a BraidDecision audit row tagged with ``case:<id>`` so the inline UI
  can filter by it
* failure path: capability raises HTTPException → hook still returns
  None and writes an audit row with ``error`` populated

We don't hit Together AI or any real LLM here — every capability is
patched at the import boundary the hook uses.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.braid.hooks import (
    check_conflict_for_filing,
    score_completeness_for_case,
    validate_nice_for_case,
)
from app.braid.models import BraidDecision
from app.cases.models import Case, CaseStatus, CaseType
from app.users.models import User


def _trademark_case(client_user: User, lawyer_user: User) -> Case:
    return Case(
        case_number="ETR-2026-BRAID-1",
        title="Acme Wordmark",
        description="A premium coffee chain selling artisanal espresso drinks.",
        case_type=CaseType.trademark,
        status=CaseStatus.open,
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id,
        jurisdiction="EU",
        nice_classes="30,43",
    )


@pytest.fixture(autouse=True)
def _braid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hooks no-op if BRAID_INTERNAL_TOKEN is unset; force-enable here."""
    from app.config import settings

    monkeypatch.setattr(settings, "braid_internal_token", "test-token")


# ---------------------------------------------------------------------------
# validate_nice_for_case
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_validate_nice_skips_non_trademark_case(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> None:
    case = _trademark_case(client_user, lawyer_user)
    case.case_type = CaseType.patent
    db_session.add(case)
    await db_session.flush()

    with patch(
        "app.braid.router.validate_nice_classification", new=AsyncMock()
    ) as mock_handler:
        await validate_nice_for_case(db_session, case)

    mock_handler.assert_not_called()


@pytest.mark.integration
async def test_validate_nice_skips_when_no_classes(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> None:
    case = _trademark_case(client_user, lawyer_user)
    case.nice_classes = None
    db_session.add(case)
    await db_session.flush()

    with patch(
        "app.braid.router.validate_nice_classification", new=AsyncMock()
    ) as mock_handler:
        await validate_nice_for_case(db_session, case)

    mock_handler.assert_not_called()


@pytest.mark.integration
async def test_validate_nice_audits_success(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> None:
    case = _trademark_case(client_user, lawyer_user)
    db_session.add(case)
    await db_session.flush()

    fake_response = AsyncMock()
    fake_response.model_dump = lambda mode=None: {
        "classes_consistent": True,
        "confidence": 0.92,
    }

    handler_mock = AsyncMock(return_value=fake_response)
    with patch(
        "app.braid.router.validate_nice_classification", new=handler_mock
    ):
        await validate_nice_for_case(db_session, case)

    handler_mock.assert_awaited_once()

    rows = (
        await db_session.execute(
            select(BraidDecision).where(
                BraidDecision.capability_name == "validate_nice_classification"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_message == f"case:{case.id}"
    assert rows[0].error is None
    assert rows[0].args["proposed_classes"] == [30, 43]


@pytest.mark.integration
async def test_validate_nice_swallows_capability_failure(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> None:
    """A 502/503 from the capability must not propagate; the hook must
    still record an audit row with the error so operators can see it."""
    from fastapi import HTTPException

    case = _trademark_case(client_user, lawyer_user)
    db_session.add(case)
    await db_session.flush()

    handler_mock = AsyncMock(
        side_effect=HTTPException(status_code=502, detail="together api down")
    )
    with patch(
        "app.braid.router.validate_nice_classification", new=handler_mock
    ):
        # The hook itself must not raise.
        await validate_nice_for_case(db_session, case)

    rows = (
        await db_session.execute(
            select(BraidDecision).where(
                BraidDecision.capability_name == "validate_nice_classification"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].error and "together api down" in rows[0].error


# ---------------------------------------------------------------------------
# score_completeness_for_case
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_completeness_audits_success(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> None:
    case = _trademark_case(client_user, lawyer_user)
    db_session.add(case)
    await db_session.flush()

    fake_response = AsyncMock()
    fake_response.model_dump = lambda mode=None: {
        "ready_to_file": True,
        "completeness_pct": 1.0,
    }

    handler_mock = AsyncMock(return_value=fake_response)
    with patch(
        "app.braid.router.score_document_completeness", new=handler_mock
    ):
        await score_completeness_for_case(db_session, case)

    handler_mock.assert_awaited_once()

    rows = (
        await db_session.execute(
            select(BraidDecision).where(
                BraidDecision.capability_name == "score_document_completeness"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_message == f"case:{case.id}"


# ---------------------------------------------------------------------------
# check_conflict_for_filing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_conflict_skips_unsupported_jurisdiction(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> None:
    case = _trademark_case(client_user, lawyer_user)
    db_session.add(case)
    await db_session.flush()

    handler_mock = AsyncMock()
    with patch(
        "app.braid.router.check_trademark_conflict", new=handler_mock
    ):
        await check_conflict_for_filing(
            db_session,
            submission_id=uuid.uuid4(),
            case_id=case.id,
            mark_text="ACME",
            nice_classes=[30],
            jurisdiction="tr",
        )
    handler_mock.assert_not_called()


@pytest.mark.integration
async def test_conflict_audits_success(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> None:
    case = _trademark_case(client_user, lawyer_user)
    db_session.add(case)
    await db_session.flush()
    submission_id = uuid.uuid4()

    fake_response = AsyncMock()
    fake_response.model_dump = lambda mode=None: {
        "match_count": 0,
        "risk_level": "none",
    }

    handler_mock = AsyncMock(return_value=fake_response)
    with patch(
        "app.braid.router.check_trademark_conflict", new=handler_mock
    ):
        await check_conflict_for_filing(
            db_session,
            submission_id=submission_id,
            case_id=case.id,
            mark_text="ACME",
            nice_classes=[30],
            jurisdiction="uk",
        )

    handler_mock.assert_awaited_once()
    rows = (
        await db_session.execute(
            select(BraidDecision).where(
                BraidDecision.capability_name == "check_trademark_conflict"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert f"case:{case.id}" in rows[0].user_message
    assert f"submission:{submission_id}" in rows[0].user_message


# ---------------------------------------------------------------------------
# Disabled mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_hooks_noop_when_braid_token_unset(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "braid_internal_token", "")

    case = _trademark_case(client_user, lawyer_user)
    db_session.add(case)
    await db_session.flush()

    with patch(
        "app.braid.router.validate_nice_classification", new=AsyncMock()
    ) as nice_mock, patch(
        "app.braid.router.score_document_completeness", new=AsyncMock()
    ) as comp_mock, patch(
        "app.braid.router.check_trademark_conflict", new=AsyncMock()
    ) as conflict_mock:
        await validate_nice_for_case(db_session, case)
        await score_completeness_for_case(db_session, case)
        await check_conflict_for_filing(
            db_session,
            submission_id=uuid.uuid4(),
            case_id=case.id,
            mark_text="ACME",
            nice_classes=[30],
            jurisdiction="uk",
        )

    nice_mock.assert_not_called()
    comp_mock.assert_not_called()
    conflict_mock.assert_not_called()

"""Tests for the UKIPO Stripe webhook handler (issue #36, Step 3).

Targets ``_handle_ukipo_session_completed`` in app/payments/service.py —
the module CI's coverage report showed at 14%, and the exact function
whose missing ``await`` (during the #21 async refactor) shipped through
a green CI run. These tests exercise the early-return branches with a
real (SQLite) DB session, and one full happy-path run with the Vault/
prover/on-chain calls mocked out.
"""
from __future__ import annotations

import base64
import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.payments.service import _handle_ukipo_session_completed
from app.services.ukipo.models import (
    UKIPOMarkType,
    UKIPOOwnerEntityType,
    UKIPOSubmission,
    UKIPOSubmissionStatus,
)


async def _make_submission(
    db_session: AsyncSession, **overrides
) -> UKIPOSubmission:
    """Insert a minimal-but-valid UKIPOSubmission row.

    SQLite (the test DB) does not enforce foreign keys by default, so
    ``case_id`` can be a random UUID without a matching ``cases`` row —
    the handler under test never dereferences the Case itself.
    """
    defaults = dict(
        case_id=uuid.uuid4(),
        owner_company_name="Acme Ltd",
        owner_country="United Kingdom",
        owner_address_line1="1 Example Street",
        owner_city="London",
        owner_entity_type=UKIPOOwnerEntityType.registered_company_or_llp,
        mark_type=UKIPOMarkType.word,
        mark_text="ACME",
        nice_classes_json=json.dumps([{"class_number": 9}]),
        status=UKIPOSubmissionStatus.awaiting_payment,
    )
    defaults.update(overrides)
    submission = UKIPOSubmission(**defaults)
    db_session.add(submission)
    await db_session.flush()
    await db_session.refresh(submission)
    return submission


@pytest.mark.integration
async def test_missing_submission_id_returns_early(
    db_session: AsyncSession,
) -> None:
    session = {"metadata": {}}
    result = await _handle_ukipo_session_completed(db_session, session)
    assert result == {"handled": False, "reason": "missing_submission_id"}


@pytest.mark.integration
async def test_invalid_submission_id_returns_early(
    db_session: AsyncSession,
) -> None:
    session = {"metadata": {"submission_id": "not-a-uuid"}}
    result = await _handle_ukipo_session_completed(db_session, session)
    assert result == {"handled": False, "reason": "missing_submission_id"}


@pytest.mark.integration
async def test_submission_not_found_returns_early(
    db_session: AsyncSession,
) -> None:
    session = {"metadata": {"submission_id": str(uuid.uuid4())}}
    result = await _handle_ukipo_session_completed(db_session, session)
    assert result == {"handled": False, "reason": "submission_not_found"}


@pytest.mark.integration
async def test_already_filed_returns_early(
    db_session: AsyncSession,
) -> None:
    submission = await _make_submission(
        db_session, status=UKIPOSubmissionStatus.filed
    )
    session = {"metadata": {"submission_id": str(submission.id)}}
    result = await _handle_ukipo_session_completed(db_session, session)
    assert result == {"handled": False, "reason": "already_filed"}


@pytest.mark.integration
async def test_pending_async_payment_returns_early(
    db_session: AsyncSession,
) -> None:
    submission = await _make_submission(db_session)
    session = {
        "metadata": {"submission_id": str(submission.id)},
        "payment_status": "unpaid",
    }
    result = await _handle_ukipo_session_completed(db_session, session)
    assert result == {"handled": True, "status": "pending_async_payment"}


@pytest.mark.integration
async def test_happy_path_marks_submission_filed(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Full success path with Vault/prover/on-chain calls mocked out.

    solana_zk_verifier_enabled is turned off so the on-chain
    attestation branch (a separate Vault + Solana RPC round-trip,
    already covered by test_signer_backends.py) is not exercised here
    — this test's job is the webhook's own state-transition logic.
    """
    monkeypatch.setattr(settings, "solana_zk_verifier_enabled", False)

    async def _fake_derive_secret(*, stripe_payment_intent_id, query_hash):
        return 12345

    fake_prover_output = {
        "commitment_dec": "42",
        "onchain": {
            "proof_a_b64": base64.b64encode(b"a" * 64).decode("ascii"),
            "proof_b_b64": base64.b64encode(b"b" * 128).decode("ascii"),
            "proof_c_b64": base64.b64encode(b"c" * 64).decode("ascii"),
            "public_inputs_b64": [
                base64.b64encode(b"i" * 32).decode("ascii")
            ],
        },
    }

    async def _fake_run_prover(*, secret, query_hash):
        return fake_prover_output

    import app.compliance.service as compliance_service_module

    monkeypatch.setattr(
        compliance_service_module, "derive_secret", _fake_derive_secret
    )
    monkeypatch.setattr(
        compliance_service_module, "_run_prover", _fake_run_prover
    )

    submission = await _make_submission(db_session)
    session = {
        "metadata": {"submission_id": str(submission.id)},
        "payment_status": "paid",
        "payment_intent": "pi_test_123",
    }

    result = await _handle_ukipo_session_completed(db_session, session)

    assert result["handled"] is True
    assert result["status"] == "filed"
    assert result["submission_id"] == str(submission.id)

    await db_session.refresh(submission)
    assert submission.status == UKIPOSubmissionStatus.filed
    assert submission.finished_at is not None
    assert submission.stripe_payment_intent_id == "pi_test_123"
    assert submission.solana_commitment_hex is not None

"""Tests for the UKIPO Stripe webhook handler (issue #36, Step 3).

Targets ``_handle_ukipo_session_completed`` in app/payments/service.py.
The #21 async refactor left ``_load_operator`` and ``derive_secret``
unawaited here and CI stayed green, so these tests are written to fail
if either await is dropped:

* the prover fake records the secret it receives (an un-awaited
  ``derive_secret`` would hand it a coroutine, not the real value);
* a happy path runs with ``solana_zk_verifier_enabled=True`` so the
  ``_load_operator`` / ``submit_compliance_proof_tx`` branch executes
  (an un-awaited ``_load_operator`` raises AttributeError there and the
  handler would return ``attestation_failed`` instead of ``filed``).
"""
from __future__ import annotations

import base64
import json
import uuid

import pytest
from solders.pubkey import Pubkey
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.payments.service import _handle_ukipo_session_completed
from app.services.ukipo.models import (
    UKIPOMarkType,
    UKIPOOwnerEntityType,
    UKIPOSubmission,
    UKIPOSubmissionStatus,
)

_SECRET = 12345

_PROVER_OUTPUT = {
    "commitment_dec": "42",
    "onchain": {
        "proof_a_b64": base64.b64encode(b"a" * 64).decode("ascii"),
        "proof_b_b64": base64.b64encode(b"b" * 128).decode("ascii"),
        "proof_c_b64": base64.b64encode(b"c" * 64).decode("ascii"),
        "public_inputs_b64": [base64.b64encode(b"i" * 32).decode("ascii")],
    },
}


async def _make_submission(
    db_session: AsyncSession, **overrides
) -> UKIPOSubmission:
    """Insert a minimal-but-valid UKIPOSubmission row.

    SQLite (the test DB) does not enforce foreign keys by default, so
    ``case_id`` can be a random UUID without a matching ``cases`` row.
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


def _paid_session(submission: UKIPOSubmission) -> dict:
    return {
        "metadata": {"submission_id": str(submission.id)},
        "payment_status": "paid",
        "payment_intent": "pi_test_123",
    }


def _patch_compliance(
    monkeypatch, *, captured_secrets: list, prover_error: Exception | None = None
) -> None:
    """Replace derive_secret / _run_prover on app.compliance.service.

    The handler imports them inside the function body, so patching the
    module attributes is enough. The prover fake *records* the secret it
    receives instead of ignoring it.
    """

    async def _fake_derive_secret(*, stripe_payment_intent_id, query_hash):
        return _SECRET

    async def _fake_run_prover(*, secret, query_hash):
        captured_secrets.append(secret)
        if prover_error is not None:
            raise prover_error
        return _PROVER_OUTPUT

    import app.compliance.service as compliance_service_module

    monkeypatch.setattr(
        compliance_service_module, "derive_secret", _fake_derive_secret
    )
    monkeypatch.setattr(
        compliance_service_module, "_run_prover", _fake_run_prover
    )


class _FakeOperator:
    def pubkey(self) -> Pubkey:
        return Pubkey.default()


def _patch_onchain(
    monkeypatch, *, calls: list, submit_error: Exception | None = None
) -> None:
    """Replace the on-chain pieces the handler imports from app.solana.client."""

    async def _fake_load_operator(caller_context="unknown", op_kind="sign"):
        calls.append(("load_operator", caller_context))
        return _FakeOperator()

    async def _fake_submit(*args, **kwargs):
        calls.append(("submit", None))
        if submit_error is not None:
            raise submit_error
        return "sig_test_abc", Pubkey.default()

    import app.solana.client as solana_client_module

    monkeypatch.setattr(solana_client_module, "_load_operator", _fake_load_operator)
    monkeypatch.setattr(
        solana_client_module, "submit_compliance_proof_tx", _fake_submit
    )


# ---------------------------------------------------------------------------
# Early-return branches (real test DB, nothing mocked)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_missing_submission_id_returns_early(
    db_session: AsyncSession,
) -> None:
    result = await _handle_ukipo_session_completed(
        db_session, {"metadata": {}}
    )
    assert result == {"handled": False, "reason": "missing_submission_id"}


@pytest.mark.integration
async def test_invalid_submission_id_returns_early(
    db_session: AsyncSession,
) -> None:
    result = await _handle_ukipo_session_completed(
        db_session, {"metadata": {"submission_id": "not-a-uuid"}}
    )
    assert result == {"handled": False, "reason": "missing_submission_id"}


@pytest.mark.integration
async def test_submission_not_found_returns_early(
    db_session: AsyncSession,
) -> None:
    result = await _handle_ukipo_session_completed(
        db_session, {"metadata": {"submission_id": str(uuid.uuid4())}}
    )
    assert result == {"handled": False, "reason": "submission_not_found"}


@pytest.mark.integration
async def test_already_filed_returns_early(db_session: AsyncSession) -> None:
    submission = await _make_submission(
        db_session, status=UKIPOSubmissionStatus.filed
    )
    result = await _handle_ukipo_session_completed(
        db_session, {"metadata": {"submission_id": str(submission.id)}}
    )
    assert result == {"handled": False, "reason": "already_filed"}


@pytest.mark.integration
async def test_pending_async_payment_returns_early(
    db_session: AsyncSession,
) -> None:
    submission = await _make_submission(db_session)
    result = await _handle_ukipo_session_completed(
        db_session,
        {
            "metadata": {"submission_id": str(submission.id)},
            "payment_status": "unpaid",
        },
    )
    assert result == {"handled": True, "status": "pending_async_payment"}


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_happy_path_passes_real_secret_to_prover(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Verifier disabled: the prover must still receive the awaited secret."""
    monkeypatch.setattr(settings, "solana_zk_verifier_enabled", False)
    captured: list = []
    _patch_compliance(monkeypatch, captured_secrets=captured)

    submission = await _make_submission(db_session)
    result = await _handle_ukipo_session_completed(
        db_session, _paid_session(submission)
    )

    assert result["status"] == "filed"
    # Fails if ``derive_secret`` loses its await: the prover would get a
    # coroutine object here instead of the resolved value.
    assert captured == [_SECRET]

    await db_session.refresh(submission)
    assert submission.status == UKIPOSubmissionStatus.filed
    assert submission.finished_at is not None
    assert submission.stripe_payment_intent_id == "pi_test_123"
    assert submission.solana_commitment_hex is not None


@pytest.mark.integration
async def test_happy_path_with_onchain_attestation_enabled(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Production default (verifier enabled): the on-chain branch must run."""
    monkeypatch.setattr(settings, "solana_zk_verifier_enabled", True)
    captured: list = []
    onchain_calls: list = []
    _patch_compliance(monkeypatch, captured_secrets=captured)
    _patch_onchain(monkeypatch, calls=onchain_calls)

    submission = await _make_submission(db_session)
    result = await _handle_ukipo_session_completed(
        db_session, _paid_session(submission)
    )

    assert result["status"] == "filed"
    assert result["compliance_tx"] == "sig_test_abc"
    assert captured == [_SECRET]
    # Fails if ``_load_operator`` loses its await: ``operator.pubkey()``
    # would raise AttributeError and the handler would return
    # ``attestation_failed`` instead of ``filed``.
    assert ("load_operator", "payments.ukipo_compliance_attestation") in onchain_calls
    assert ("submit", None) in onchain_calls

    await db_session.refresh(submission)
    assert submission.status == UKIPOSubmissionStatus.filed
    assert submission.solana_compliance_tx == "sig_test_abc"
    assert submission.solana_compliance_pda == str(Pubkey.default())


# ---------------------------------------------------------------------------
# Failure branches
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_prover_failure_is_reported_and_payment_is_recorded(
    db_session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "solana_zk_verifier_enabled", True)
    captured: list = []
    onchain_calls: list = []
    _patch_compliance(
        monkeypatch,
        captured_secrets=captured,
        prover_error=RuntimeError("prover exploded"),
    )
    _patch_onchain(monkeypatch, calls=onchain_calls)

    submission = await _make_submission(db_session)
    result = await _handle_ukipo_session_completed(
        db_session, _paid_session(submission)
    )

    assert result["handled"] is True
    assert result["status"] == "prover_failed"
    assert "prover exploded" in result["error"]
    # The on-chain step must not run after a prover failure.
    assert onchain_calls == []

    await db_session.refresh(submission)
    # The Stripe payment itself is recorded even though filing did not
    # complete; the submission stays at awaiting_payment so a webhook
    # redelivery can retry it.
    assert submission.stripe_payment_intent_id == "pi_test_123"
    assert submission.stripe_confirmed_at is not None
    assert submission.status == UKIPOSubmissionStatus.awaiting_payment
    assert submission.solana_compliance_tx is None


@pytest.mark.integration
async def test_attestation_failure_is_reported_and_payment_is_recorded(
    db_session: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "solana_zk_verifier_enabled", True)
    captured: list = []
    onchain_calls: list = []
    _patch_compliance(monkeypatch, captured_secrets=captured)
    _patch_onchain(
        monkeypatch,
        calls=onchain_calls,
        submit_error=RuntimeError("rpc unavailable"),
    )

    submission = await _make_submission(db_session)
    result = await _handle_ukipo_session_completed(
        db_session, _paid_session(submission)
    )

    assert result["handled"] is True
    assert result["status"] == "attestation_failed"
    assert "rpc unavailable" in result["error"]

    await db_session.refresh(submission)
    assert submission.stripe_confirmed_at is not None
    assert submission.status == UKIPOSubmissionStatus.awaiting_payment
    assert submission.solana_compliance_tx is None

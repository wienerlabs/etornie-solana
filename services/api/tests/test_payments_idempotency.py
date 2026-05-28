"""Database-level idempotency tests for the payments table.

Stripe sends the same ``checkout.session.completed`` event up to
three times when our webhook responds slowly; the success_url
reconcile path may also race the webhook. Both routes converge on
the same ``PaymentIntent`` row via the ``idempotency_key`` unique
constraint — these tests pin that contract.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.agent.models import (
    ApplicantType,
    CaseDraft,
    CaseDraftStatus,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentProvider,
    PaymentType,
)
from app.cases.models import CaseType
from app.users.models import AuthMethod, User, UserRole


async def _make_user(db) -> User:  # type: ignore[no-untyped-def]
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x" * 60,
        full_name="Test User",
        role=UserRole.client,
        auth_method=AuthMethod.email.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_draft(db, user_id: uuid.UUID) -> CaseDraft:  # type: ignore[no-untyped-def]
    session_id = uuid.uuid4()
    # AgentSession FK is required; insert a row directly so the draft
    # has somewhere to anchor.
    from app.agent.models import AgentSession

    session = AgentSession(
        id=session_id,
        user_id=user_id,
        title="t",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
    )
    db.add(session)
    await db.flush()

    draft = CaseDraft(
        session_id=session_id,
        user_id=user_id,
        case_type=CaseType.trademark,
        mark_text="TestMark",
        applicant_name="Test Co",
        applicant_type=ApplicantType.legal_entity,
        target_countries=["Germany"],
        selected_platforms=["EUIPO"],
        nice_classes=[9, 42],
        status=CaseDraftStatus.validated,
    )
    db.add(draft)
    await db.flush()
    return draft


@pytest.mark.integration
async def test_duplicate_idempotency_key_rejected(setup_database) -> None:  # type: ignore[no-untyped-def]
    """Re-inserting the same (case_draft, platform) idempotency_key fails.

    This is exactly what protects us from a doubled webhook delivery:
    the second insert hits the unique constraint and the existing row
    wins (our service layer falls back to ``find_one_or_none``).
    """
    from tests.conftest import async_session_test

    async with async_session_test() as db:
        user = await _make_user(db)
        draft = await _make_draft(db, user.id)
        key = f"draft:{draft.id}:platform_fee:EUIPO:stripe"

        first = PaymentIntent(
            case_draft_id=draft.id,
            payment_type=PaymentType.platform_fee,
            provider=PaymentProvider.stripe,
            amount=Decimal("900"),
            currency="EUR",
            status=PaymentIntentStatus.created,
            idempotency_key=key,
        )
        db.add(first)
        await db.commit()

        # Same key → IntegrityError.
        duplicate = PaymentIntent(
            case_draft_id=draft.id,
            payment_type=PaymentType.platform_fee,
            provider=PaymentProvider.stripe,
            amount=Decimal("900"),
            currency="EUR",
            status=PaymentIntentStatus.created,
            idempotency_key=key,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.integration
async def test_different_provider_can_share_draft(setup_database) -> None:  # type: ignore[no-untyped-def]
    """x402 + Stripe intents on the same draft both fit — different
    idempotency keys (different provider suffix)."""
    from tests.conftest import async_session_test

    async with async_session_test() as db:
        user = await _make_user(db)
        draft = await _make_draft(db, user.id)

        x402_intent = PaymentIntent(
            case_draft_id=draft.id,
            payment_type=PaymentType.platform_fee,
            provider=PaymentProvider.x402,
            amount=Decimal("900"),
            currency="EUR",
            status=PaymentIntentStatus.created,
            idempotency_key=f"draft:{draft.id}:platform_fee:EUIPO",
        )
        stripe_intent = PaymentIntent(
            case_draft_id=draft.id,
            payment_type=PaymentType.platform_fee,
            provider=PaymentProvider.stripe,
            amount=Decimal("900"),
            currency="EUR",
            status=PaymentIntentStatus.created,
            idempotency_key=f"draft:{draft.id}:platform_fee:EUIPO:stripe",
        )
        db.add(x402_intent)
        db.add(stripe_intent)
        await db.commit()
        # Both rows persisted — no constraint violation.
        assert x402_intent.id is not None
        assert stripe_intent.id is not None
        assert x402_intent.id != stripe_intent.id

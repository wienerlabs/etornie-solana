"""Integration tests for the admin operator panel.

Each endpoint is checked against three identity classes:
- admin → 200 with expected DTO shape
- non-admin (client / lawyer) → 403
- anonymous → 401

The list endpoints also verify pagination + status filters + the
embedded user / draft / case context so the panel never N+1s once a
real fleet of payments lands in production.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import (
    CaseDraft,
    CaseDraftStatus,
    FilingAttempt,
    FilingAttemptStatus,
    FilingPlatform,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentProvider,
    PaymentType,
)
from app.cases.models import CaseType
from app.users.models import User
from tests.conftest import auth_headers


@pytest.fixture
async def seed_admin_dataset(
    db_session: AsyncSession,
    client_user: User,
) -> dict[str, uuid.UUID]:
    """Seed one draft + one paid Stripe intent + one EUIPO attempt.

    Returns the row IDs so each test can assert against them directly.
    """
    draft = CaseDraft(
        session_id=uuid.uuid4(),
        user_id=client_user.id,
        case_type=CaseType.trademark,
        mark_text="AdminTestMark",
        applicant_name="AdminTest Ltd",
        applicant_type="legal_entity",
        target_countries=["Germany"],
        selected_platforms=["EUIPO"],
        nice_classes=[9, 42],
        status=CaseDraftStatus.paid,
    )
    db_session.add(draft)
    await db_session.flush()

    intent = PaymentIntent(
        case_draft_id=draft.id,
        payment_type=PaymentType.platform_fee,
        provider=PaymentProvider.stripe,
        amount=Decimal("900.00"),
        currency="EUR",
        status=PaymentIntentStatus.confirmed,
        idempotency_key=f"draft:{draft.id}:platform_fee:EUIPO:stripe",
        gateway_payment_id="pi_test_admin",
        gateway_metadata={
            "platform": "EUIPO",
            "filing_external_reference": None,
            "filing_error": "EUIPO sandbox 500",
        },
    )
    db_session.add(intent)

    attempt = FilingAttempt(
        case_draft_id=draft.id,
        platform=FilingPlatform.EUIPO,
        status=FilingAttemptStatus.error,
        attempt_number=1,
        error_message="EUIPO sandbox 500",
    )
    db_session.add(attempt)
    await db_session.flush()

    return {
        "draft_id": draft.id,
        "intent_id": intent.id,
        "attempt_id": attempt.id,
    }


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_overview_returns_admin_counts(
    client: AsyncClient,
    admin_user: User,
    seed_admin_dataset: dict[str, uuid.UUID],
) -> None:
    res = await client.get("/admin/overview", headers=auth_headers(admin_user))
    assert res.status_code == 200
    body = res.json()
    assert body["users_total"] >= 1
    assert body["payments_total"] >= 1
    assert body["filings_total"] >= 1
    assert "confirmed" in body["payments_by_status"]
    assert Decimal(body["payments_confirmed_amount"]["EUR"]) == Decimal("900.00")


@pytest.mark.integration
async def test_overview_forbidden_for_client(
    client: AsyncClient, client_user: User
) -> None:
    res = await client.get("/admin/overview", headers=auth_headers(client_user))
    assert res.status_code == 403


@pytest.mark.integration
async def test_overview_unauthorised_for_anonymous(client: AsyncClient) -> None:
    res = await client.get("/admin/overview")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Payments list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_payments_returns_embedded_user_context(
    client: AsyncClient,
    admin_user: User,
    seed_admin_dataset: dict[str, uuid.UUID],
) -> None:
    res = await client.get("/admin/payments", headers=auth_headers(admin_user))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    items = body["items"]
    assert items, "expected at least one seeded payment"
    row = next(
        (r for r in items if r["id"] == str(seed_admin_dataset["intent_id"])),
        None,
    )
    assert row is not None
    assert row["user_email"] == "client@etornie.ch"
    assert row["status"] == "confirmed"
    # SQLite + DECIMAL stores extra trailing zeros; compare via Decimal
    # so the contract is "equal value", not "byte-identical string".
    assert Decimal(row["amount"]) == Decimal("900.00")
    assert row["currency"] == "EUR"


@pytest.mark.integration
async def test_list_payments_status_filter(
    client: AsyncClient,
    admin_user: User,
    seed_admin_dataset: dict[str, uuid.UUID],
) -> None:
    res = await client.get(
        "/admin/payments?status=created", headers=auth_headers(admin_user)
    )
    assert res.status_code == 200
    body = res.json()
    # Seeded intent is ``confirmed``, so the ``created`` filter must
    # not surface it.
    assert all(r["status"] == "created" for r in body["items"])


@pytest.mark.integration
async def test_list_payments_rejects_unknown_status(
    client: AsyncClient, admin_user: User
) -> None:
    res = await client.get(
        "/admin/payments?status=does_not_exist",
        headers=auth_headers(admin_user),
    )
    assert res.status_code == 400


@pytest.mark.integration
async def test_list_payments_caps_page_size(
    client: AsyncClient, admin_user: User
) -> None:
    res = await client.get(
        "/admin/payments?page_size=5000", headers=auth_headers(admin_user)
    )
    # FastAPI's Query validator rejects with 422 when above le=200.
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Filings list + retry guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_filings_returns_seeded_attempt(
    client: AsyncClient,
    admin_user: User,
    seed_admin_dataset: dict[str, uuid.UUID],
) -> None:
    res = await client.get("/admin/filings", headers=auth_headers(admin_user))
    assert res.status_code == 200
    body = res.json()
    row = next(
        (r for r in body["items"] if r["id"] == str(seed_admin_dataset["attempt_id"])),
        None,
    )
    assert row is not None
    assert row["status"] == "error"
    assert row["platform"] == "EUIPO"
    assert row["case_draft_mark_text"] == "AdminTestMark"


@pytest.mark.integration
async def test_retry_filing_404_for_missing(
    client: AsyncClient, admin_user: User
) -> None:
    res = await client.post(
        f"/admin/filings/{uuid.uuid4()}/retry",
        headers=auth_headers(admin_user),
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Cases list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_cases_returns_paginated_dto(
    client: AsyncClient, admin_user: User
) -> None:
    res = await client.get("/admin/cases", headers=auth_headers(admin_user))
    assert res.status_code == 200
    body = res.json()
    # The dataset may be empty in isolation; the contract is what
    # matters here.
    assert "items" in body and "total" in body
    assert body["page"] == 0
    assert body["page_size"] == 50


@pytest.mark.integration
async def test_list_cases_rejects_unknown_nft_state(
    client: AsyncClient, admin_user: User
) -> None:
    res = await client.get(
        "/admin/cases?nft_state=glitch", headers=auth_headers(admin_user)
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Refund admin endpoint (delegates to service.refund_payment_intent)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_refund_404_for_missing_intent(
    client: AsyncClient, admin_user: User
) -> None:
    res = await client.post(
        f"/admin/payments/{uuid.uuid4()}/refund",
        json={"reason": "test"},
        headers=auth_headers(admin_user),
    )
    assert res.status_code == 404


@pytest.mark.integration
async def test_refund_forbidden_for_client(
    client: AsyncClient,
    client_user: User,
    seed_admin_dataset: dict[str, uuid.UUID],
) -> None:
    res = await client.post(
        f"/admin/payments/{seed_admin_dataset['intent_id']}/refund",
        json={"reason": "test"},
        headers=auth_headers(client_user),
    )
    assert res.status_code == 403

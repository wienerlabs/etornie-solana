"""Tests for the Stripe subscription lane (issue #62).

No mocks: the price→plan mapping is exercised through real settings,
the webhook state-machine runs against real Organization rows in the
test DB using constructed Stripe-shaped payloads (data fixtures, not
behaviour mocks), and the paths that must call Stripe are skipped when
no STRIPE_SECRET_KEY is configured (skip ≠ mock).
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationMembershipRole,
    OrganizationPlan,
)
from app.payments import service as stripe_service
from app.payments import subscription_service as subs
from app.payments.service import StripeServiceError
from app.users.models import User
from tests.conftest import auth_headers

# A configured plan needs a Stripe Price id. These are real-shaped ids
# used only to populate the config so the mapping logic can resolve;
# no Stripe call is made with them in the non-skipped tests.
_SOLO_M = "price_solo_monthly_test"
_TEAM_M = "price_team_monthly_test"
_TEAM_A = "price_team_annual_test"


@pytest.fixture
def configured_prices():
    """Populate the subscription price ids on settings, then restore.

    Assigning real config values (not patching behaviour) so
    ``_price_map`` resolves during the test.
    """
    keys = {
        "stripe_price_solo_monthly": _SOLO_M,
        "stripe_price_team_monthly": _TEAM_M,
        "stripe_price_team_annual": _TEAM_A,
    }
    saved = {k: getattr(settings, k) for k in keys}
    for k, v in keys.items():
        setattr(settings, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)


def _subscription_payload(
    *,
    customer: str,
    price_id: str,
    status: str = "active",
    cancel_at_period_end: bool = False,
    organization_id: str | None = None,
) -> dict:
    """Stripe Subscription object shape the webhook delivers.

    Mirrors the current Stripe API: ``current_period_end`` lives on each
    line item, not at the subscription top level.
    """
    return {
        "id": f"sub_{uuid.uuid4().hex[:16]}",
        "customer": customer,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "items": {
            "data": [
                {
                    "price": {"id": price_id},
                    "current_period_end": 1924905600,  # 2031-01-01, fixed
                }
            ]
        },
        "metadata": (
            {"organization_id": organization_id} if organization_id else {}
        ),
    }


# ---------------------------------------------------------------------------
# Price ↔ plan mapping
# ---------------------------------------------------------------------------


class TestPriceMapping:
    def test_resolve_price_id(self, configured_prices) -> None:
        assert subs.resolve_price_id("team", "monthly") == _TEAM_M
        assert subs.resolve_price_id("team", "annual") == _TEAM_A
        assert subs.resolve_price_id("solo", "monthly") == _SOLO_M

    def test_resolve_unconfigured_raises(self, configured_prices) -> None:
        # solo/annual was never configured in the fixture.
        with pytest.raises(StripeServiceError):
            subs.resolve_price_id("solo", "annual")

    def test_plan_for_price_id(self, configured_prices) -> None:
        assert subs.plan_for_price_id(_TEAM_M) == "team"
        assert subs.plan_for_price_id(_SOLO_M) == "solo"
        assert subs.plan_for_price_id("price_unknown") is None
        assert subs.plan_for_price_id(None) is None


# ---------------------------------------------------------------------------
# Webhook state-machine → organization
# ---------------------------------------------------------------------------


class TestSubscriptionStateMachine:
    async def test_active_subscription_grants_plan(
        self, db_session: AsyncSession, configured_prices
    ) -> None:
        org = Organization(
            slug="acme", name="Acme", stripe_customer_id="cus_acme"
        )
        db_session.add(org)
        await db_session.flush()

        payload = _subscription_payload(customer="cus_acme", price_id=_TEAM_M)
        result = await subs._apply_subscription_to_org(db_session, payload)

        assert result["handled"] is True
        await db_session.refresh(org)
        assert org.plan == OrganizationPlan.team
        assert org.subscription_status == "active"
        assert org.subscription_price_id == _TEAM_M
        assert org.stripe_subscription_id == payload["id"]
        assert org.subscription_current_period_end is not None
        assert org.subscription_cancel_at_period_end is False

    async def test_canceled_subscription_downgrades_to_solo(
        self, db_session: AsyncSession, configured_prices
    ) -> None:
        org = Organization(
            slug="beta",
            name="Beta",
            stripe_customer_id="cus_beta",
            plan=OrganizationPlan.team,
        )
        db_session.add(org)
        await db_session.flush()

        payload = _subscription_payload(
            customer="cus_beta", price_id=_TEAM_M, status="canceled"
        )
        await subs._apply_subscription_to_org(db_session, payload)

        await db_session.refresh(org)
        assert org.plan == OrganizationPlan.solo
        assert org.subscription_status == "canceled"

    def test_invoice_subscription_id_resolution(self) -> None:
        # Current Stripe API: id under subscription_details.
        assert (
            subs.subscription_id_from_invoice(
                {"subscription_details": {"subscription": "sub_new"}}
            )
            == "sub_new"
        )
        # Newest API: under parent.subscription_details.
        assert (
            subs.subscription_id_from_invoice(
                {"parent": {"subscription_details": {"subscription": "sub_p"}}}
            )
            == "sub_p"
        )
        # Legacy top-level still works.
        assert (
            subs.subscription_id_from_invoice({"subscription": "sub_old"})
            == "sub_old"
        )
        # A one-off invoice with no subscription anywhere.
        assert subs.subscription_id_from_invoice({}) is None

    async def test_stale_deleted_event_does_not_downgrade(
        self, db_session: AsyncSession, configured_prices
    ) -> None:
        # Org is on a live subscription sub_B (paying, team plan).
        org = Organization(
            slug="delta",
            name="Delta",
            stripe_customer_id="cus_delta",
            plan=OrganizationPlan.team,
            stripe_subscription_id="sub_B",
            subscription_status="active",
        )
        db_session.add(org)
        await db_session.flush()

        # A late, out-of-order `deleted` for an OLD subscription sub_A.
        stale = _subscription_payload(
            customer="cus_delta", price_id=_TEAM_M, status="canceled"
        )
        stale["id"] = "sub_A"
        result = await subs._apply_subscription_to_org(db_session, stale)

        assert result["handled"] is False
        assert result["reason"] == "stale_subscription_event"
        await db_session.refresh(org)
        # Paying org must NOT be downgraded by the stale event.
        assert org.plan == OrganizationPlan.team
        assert org.stripe_subscription_id == "sub_B"

    async def test_org_resolved_by_metadata_when_customer_unknown(
        self, db_session: AsyncSession, configured_prices
    ) -> None:
        org = Organization(slug="gamma", name="Gamma")
        db_session.add(org)
        await db_session.flush()

        # No stripe_customer_id on the row, and the payload's customer
        # is unknown — resolution must fall back to metadata.
        payload = _subscription_payload(
            customer="cus_never_seen",
            price_id=_TEAM_A,
            organization_id=str(org.id),
        )
        result = await subs._apply_subscription_to_org(db_session, payload)

        assert result["handled"] is True
        await db_session.refresh(org)
        assert org.plan == OrganizationPlan.team
        assert org.stripe_subscription_id == payload["id"]

    async def test_unknown_org_is_ignored(
        self, db_session: AsyncSession, configured_prices
    ) -> None:
        payload = _subscription_payload(
            customer="cus_nope", price_id=_TEAM_M
        )
        result = await subs._apply_subscription_to_org(db_session, payload)
        assert result["handled"] is False
        assert result["reason"] == "organization_not_found"

    async def test_webhook_dispatch_routes_subscription_event(
        self, db_session: AsyncSession, configured_prices
    ) -> None:
        # Full path: stripe_service.handle_event must route a
        # customer.subscription.* event into the subscription lane.
        org = Organization(
            slug="delta", name="Delta", stripe_customer_id="cus_delta"
        )
        db_session.add(org)
        await db_session.flush()

        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": _subscription_payload(
                    customer="cus_delta", price_id=_TEAM_M
                )
            },
        }
        result = await stripe_service.handle_event(db_session, event)
        assert result["handled"] is True
        await db_session.refresh(org)
        assert org.plan == OrganizationPlan.team


# ---------------------------------------------------------------------------
# Endpoints (auth + scoping)
# ---------------------------------------------------------------------------


class TestLivePlanListing:
    """Requires real Stripe test keys + price ids; skipped otherwise.

    Guards the StripeObject access bug (Price objects support attribute
    access but not dict.get()) found during local testing.
    """

    @pytest.mark.skipif(
        not (
            settings.stripe_secret_key
            and settings.stripe_price_solo_monthly
        ),
        reason="Stripe test key + price ids not configured",
    )
    def test_list_available_plans_returns_live_prices(self) -> None:
        plans = subs.list_available_plans()
        assert len(plans) >= 1
        for p in plans:
            assert p["price_id"].startswith("price_")
            assert isinstance(p["unit_amount"], int)
            assert p["currency"]
            assert p["recurring_interval"] in ("month", "year")


class TestSubscriptionEndpoints:
    async def test_plans_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/payments/stripe/subscription/plans")
        assert resp.status_code == 401

    async def test_plans_empty_when_no_prices_configured(
        self, client: AsyncClient, client_user: User
    ) -> None:
        # With no plan price ids configured, the endpoint returns an
        # empty list (no Stripe call). Clear the ids deterministically so
        # the test does not depend on the developer's local .env.
        price_keys = [
            "stripe_price_solo_monthly",
            "stripe_price_solo_annual",
            "stripe_price_team_monthly",
            "stripe_price_team_annual",
        ]
        saved = {k: getattr(settings, k) for k in price_keys}
        for k in price_keys:
            setattr(settings, k, "")
        try:
            resp = await client.get(
                "/payments/stripe/subscription/plans",
                headers=auth_headers(client_user),
            )
        finally:
            for k, v in saved.items():
                setattr(settings, k, v)
        assert resp.status_code == 200
        assert resp.json() == {"plans": []}

    async def test_status_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/payments/stripe/subscription/status")
        assert resp.status_code == 401

    async def test_checkout_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/payments/stripe/subscription/checkout-session",
            json={"plan": "team", "interval": "monthly"},
        )
        assert resp.status_code == 401

    async def test_status_forbidden_for_non_member(
        self,
        client: AsyncClient,
        client_user: User,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        # Org owned by admin_user; client_user is not a member at all.
        org = Organization(slug="acme-co", name="Acme Co")
        db_session.add(org)
        await db_session.flush()
        db_session.add(
            OrganizationMembership(
                organization_id=org.id,
                user_id=admin_user.id,
                role=OrganizationMembershipRole.owner,
            )
        )
        await db_session.commit()

        # client_user is not a member of this org → 403.
        resp = await client.get(
            "/payments/stripe/subscription/status",
            params={"organization_id": str(org.id)},
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 403

    async def test_status_ok_for_org_owner(
        self,
        client: AsyncClient,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        org = Organization(slug="owned", name="Owned Org")
        db_session.add(org)
        await db_session.flush()
        db_session.add(
            OrganizationMembership(
                organization_id=org.id,
                user_id=client_user.id,
                role=OrganizationMembershipRole.owner,
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/payments/stripe/subscription/status",
            params={"organization_id": str(org.id)},
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["organization_id"] == str(org.id)
        assert body["plan"] == "solo"
        assert body["has_billing_account"] is False
        assert body["subscription_status"] is None
        assert body["can_manage"] is True

    async def test_member_can_read_status_but_not_manage(
        self,
        client: AsyncClient,
        client_user: User,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        # A plain member can read the status (can_manage=False) but is
        # refused checkout (owner/admin only).
        org = Organization(slug="team-co", name="Team Co")
        db_session.add(org)
        await db_session.flush()
        db_session.add_all(
            [
                OrganizationMembership(
                    organization_id=org.id,
                    user_id=admin_user.id,
                    role=OrganizationMembershipRole.owner,
                ),
                OrganizationMembership(
                    organization_id=org.id,
                    user_id=client_user.id,
                    role=OrganizationMembershipRole.member,
                ),
            ]
        )
        await db_session.commit()

        status_resp = await client.get(
            "/payments/stripe/subscription/status",
            params={"organization_id": str(org.id)},
            headers=auth_headers(client_user),
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["can_manage"] is False

        checkout_resp = await client.post(
            "/payments/stripe/subscription/checkout-session",
            json={
                "plan": "team",
                "interval": "monthly",
                "organization_id": str(org.id),
            },
            headers=auth_headers(client_user),
        )
        assert checkout_resp.status_code == 403

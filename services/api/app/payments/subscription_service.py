"""Stripe subscription (recurring billing) service layer.

Separate from :mod:`app.payments.service` (which owns one-off filing
payments) so the subscription state-machine stays self-contained. The
flow is org-scoped: an ``Organization`` carries the Stripe customer +
subscription ids, and the Stripe subscription's status drives
``Organization.plan`` (the entitlement the rest of the app reads).

EU VAT is handled by Stripe Tax: the Checkout session enables
``automatic_tax`` (Stripe computes + collects the right VAT per the
customer's billing country) and ``tax_id_collection`` (B2B customers
enter a VAT id, enabling reverse-charge). No tax rates live in the app.

No price is hardcoded here: plan/interval pairs resolve to Stripe Price
ids from settings, and display amounts are read live from Stripe.
"""
from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import translate_stripe_error
from app.organizations.models import Organization, OrganizationPlan
from app.payments.service import StripeServiceError, _require_configured
from app.users.models import User

logger = logging.getLogger(__name__)


class BillingInterval(str, enum.Enum):
    monthly = "monthly"
    annual = "annual"


# Subscription statuses under which the paid entitlement stays granted.
# ``past_due`` keeps access during Stripe's dunning/grace window; the
# customer is nudged by Stripe to fix payment before it flips to unpaid.
_ENTITLED_STATUSES = frozenset({"active", "trialing", "past_due"})
# Statuses that revoke the paid entitlement (downgrade to the free tier).
_REVOKED_STATUSES = frozenset(
    {"canceled", "unpaid", "incomplete_expired"}
)


def _price_map() -> dict[tuple[str, str], str]:
    """``(plan, interval) -> Stripe Price id`` for every configured plan.

    Empty ids are dropped, so an unconfigured plan/interval simply does
    not appear (and cannot be checked out).
    """
    raw = {
        (OrganizationPlan.solo.value, BillingInterval.monthly.value): (
            settings.stripe_price_solo_monthly
        ),
        (OrganizationPlan.solo.value, BillingInterval.annual.value): (
            settings.stripe_price_solo_annual
        ),
        (OrganizationPlan.team.value, BillingInterval.monthly.value): (
            settings.stripe_price_team_monthly
        ),
        (OrganizationPlan.team.value, BillingInterval.annual.value): (
            settings.stripe_price_team_annual
        ),
    }
    return {key: value for key, value in raw.items() if value}


def resolve_price_id(plan: str, interval: str) -> str:
    price_id = _price_map().get((plan, interval))
    if not price_id:
        raise StripeServiceError(
            f"No Stripe price configured for plan={plan} interval={interval}.",
            user_message=(
                "This plan is not available for the selected billing period."
            ),
            http_status=400,
        )
    return price_id


def plan_for_price_id(price_id: str | None) -> str | None:
    """Reverse lookup: which plan a Stripe Price id grants."""
    if not price_id:
        return None
    for (plan, _interval), pid in _price_map().items():
        if pid == price_id:
            return plan
    return None


def _as_dict(obj: Any) -> dict[str, Any]:
    """Normalise a Stripe object (webhook payload) into a plain dict."""
    if hasattr(obj, "to_dict_recursive"):
        return obj.to_dict_recursive()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)


# ---------------------------------------------------------------------------
# Customer + checkout
# ---------------------------------------------------------------------------


async def ensure_customer(
    db: AsyncSession, org: Organization, user: User
) -> str:
    """Return the org's Stripe customer id, creating it on first use."""
    _require_configured()
    if org.stripe_customer_id:
        return org.stripe_customer_id

    try:
        customer = stripe.Customer.create(
            name=org.name,
            email=user.email or None,
            metadata={
                "organization_id": str(org.id),
                "organization_slug": org.slug,
            },
        )
    except stripe.StripeError as exc:  # noqa: BLE001
        translated = translate_stripe_error(exc)
        raise StripeServiceError(
            f"Stripe customer creation failed: {exc}",
            user_message=translated.user_message,
            http_status=translated.http_status,
        ) from exc

    org.stripe_customer_id = customer.id
    await db.flush()
    return customer.id


async def create_subscription_checkout(
    db: AsyncSession,
    *,
    org: Organization,
    user: User,
    plan: str,
    interval: str,
) -> stripe.checkout.Session:
    """Open a ``mode=subscription`` Checkout session for an organization.

    Enables Stripe Tax (automatic VAT) and VAT-id collection so the
    session is EU-VAT compliant for both B2C and B2B customers.
    """
    _require_configured()
    price_id = resolve_price_id(plan, interval)
    customer_id = await ensure_customer(db, org, user)

    session_kwargs: dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": settings.stripe_subscription_success_url,
        "cancel_url": settings.stripe_subscription_cancel_url,
        "client_reference_id": str(org.id),
        "metadata": {
            "lane": "subscription",
            "organization_id": str(org.id),
            "plan": plan,
            "interval": interval,
        },
        "subscription_data": {
            "metadata": {
                "organization_id": str(org.id),
                "plan": plan,
                "interval": interval,
            }
        },
        # VAT: collect a billing address (Stripe Tax needs it) and a
        # business VAT id (reverse-charge for B2B). ``customer_update``
        # is required so Checkout may persist what it collects back onto
        # the existing customer.
        "billing_address_collection": "required",
        "tax_id_collection": {"enabled": True},
        "customer_update": {"address": "auto", "name": "auto"},
    }
    if settings.stripe_tax_enabled:
        session_kwargs["automatic_tax"] = {"enabled": True}

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.StripeError as exc:  # noqa: BLE001
        logger.exception("Stripe subscription checkout.Session.create failed")
        translated = translate_stripe_error(exc)
        raise StripeServiceError(
            f"Stripe rejected the subscription session: {exc}",
            user_message=translated.user_message,
            http_status=translated.http_status,
        ) from exc

    await db.commit()
    return session


async def create_billing_portal_session(
    *, org: Organization
) -> stripe.billing_portal.Session:
    """Open a Stripe Billing Portal session so the org can self-manage.

    The portal lets the customer update card, switch plan, download
    invoices, and cancel — all handled by Stripe, mirrored back to us
    through the subscription webhooks.
    """
    _require_configured()
    if not org.stripe_customer_id:
        raise StripeServiceError(
            f"Organization {org.id} has no Stripe customer; cannot open portal.",
            user_message=(
                "You do not have a billing account yet — subscribe to a "
                "plan first."
            ),
            http_status=400,
        )
    try:
        return stripe.billing_portal.Session.create(
            customer=org.stripe_customer_id,
            return_url=settings.stripe_billing_portal_return_url,
        )
    except stripe.StripeError as exc:  # noqa: BLE001
        translated = translate_stripe_error(exc)
        raise StripeServiceError(
            f"Stripe billing portal creation failed: {exc}",
            user_message=translated.user_message,
            http_status=translated.http_status,
        ) from exc


def list_available_plans() -> list[dict[str, Any]]:
    """Configured plans with live amounts pulled from Stripe.

    Amounts come straight from the Stripe Price objects so the app never
    stores or guesses a price. ``unit_amount`` is in minor units.
    """
    _require_configured()
    plans: list[dict[str, Any]] = []
    for (plan, interval), price_id in sorted(_price_map().items()):
        try:
            price = stripe.Price.retrieve(price_id)
        except stripe.StripeError as exc:  # noqa: BLE001
            logger.warning(
                "Skipping plan %s/%s — Stripe price %s not retrievable: %s",
                plan,
                interval,
                price_id,
                exc,
            )
            continue
        # Stripe objects support attribute / subscript access but NOT
        # dict.get(), so read fields with getattr and defaults.
        recurring = getattr(price, "recurring", None)
        plans.append(
            {
                "plan": plan,
                "interval": interval,
                "price_id": price_id,
                "unit_amount": getattr(price, "unit_amount", None),
                "currency": getattr(price, "currency", None),
                "recurring_interval": (
                    getattr(recurring, "interval", None) if recurring else None
                ),
                "recurring_interval_count": (
                    getattr(recurring, "interval_count", None)
                    if recurring
                    else None
                ),
            }
        )
    return plans


# ---------------------------------------------------------------------------
# Webhook → organization state
# ---------------------------------------------------------------------------


async def _find_org_for_subscription(
    db: AsyncSession, sub: dict[str, Any]
) -> Organization | None:
    customer_id = sub.get("customer")
    if customer_id:
        org = (
            await db.execute(
                select(Organization).where(
                    Organization.stripe_customer_id == customer_id
                )
            )
        ).scalar_one_or_none()
        if org is not None:
            return org

    org_id = (sub.get("metadata") or {}).get("organization_id")
    if org_id:
        try:
            oid = uuid.UUID(org_id)
        except (TypeError, ValueError):
            oid = None
        if oid is not None:
            return (
                await db.execute(
                    select(Organization).where(Organization.id == oid)
                )
            ).scalar_one_or_none()
    return None


def subscription_id_from_invoice(invoice: dict[str, Any]) -> str | None:
    """Resolve the subscription id from an invoice across Stripe versions.

    ``invoice.subscription`` was removed in recent Stripe API versions; the
    id now lives under ``subscription_details`` and, in the newest versions,
    under ``parent.subscription_details``. We check all three so the dunning
    lane works regardless of the account's API version.
    """
    return (
        invoice.get("subscription")
        or (invoice.get("subscription_details") or {}).get("subscription")
        or (
            (invoice.get("parent") or {}).get("subscription_details") or {}
        ).get("subscription")
    )


async def _apply_subscription_to_org(
    db: AsyncSession, subscription: Any
) -> dict[str, Any]:
    """Mirror a Stripe subscription onto its organization row.

    Updates the billing columns and drives ``Organization.plan``: the
    plan is granted while the subscription is entitled and downgraded to
    the free ``solo`` tier when it is revoked.
    """
    sub = _as_dict(subscription)
    org = await _find_org_for_subscription(db, sub)
    if org is None:
        logger.warning(
            "Stripe subscription %s has no matching organization",
            sub.get("id"),
        )
        return {"handled": False, "reason": "organization_not_found"}

    status_str = sub.get("status")
    sub_id = sub.get("id")
    items = (sub.get("items") or {}).get("data") or []
    price_id = None
    if items:
        price_id = (items[0].get("price") or {}).get("id")

    # ``current_period_end`` moved from the subscription top level onto each
    # line item in recent Stripe API versions (2025+); read the item value
    # and fall back to the legacy top-level field for older versions.
    period_end = sub.get("current_period_end")
    if period_end is None and items:
        period_end = items[0].get("current_period_end")

    # Ordering / idempotency guard: a stale, out-of-order revoked event
    # (e.g. a late ``customer.subscription.deleted`` for a subscription the
    # org has already replaced with a new active one) must never downgrade a
    # paying org. Only act on a revoked status when it concerns the
    # subscription we currently track.
    is_revoked = status_str in _REVOKED_STATUSES
    if (
        is_revoked
        and org.stripe_subscription_id
        and sub_id
        and org.stripe_subscription_id != sub_id
    ):
        return {
            "handled": False,
            "reason": "stale_subscription_event",
            "organization_id": str(org.id),
        }

    org.stripe_subscription_id = sub_id
    org.subscription_status = status_str
    org.subscription_price_id = price_id
    org.subscription_current_period_end = (
        datetime.fromtimestamp(period_end, tz=timezone.utc)
        if period_end
        else None
    )
    org.subscription_cancel_at_period_end = bool(
        sub.get("cancel_at_period_end")
    )

    if status_str in _ENTITLED_STATUSES:
        plan = plan_for_price_id(price_id)
        if plan is not None:
            org.plan = OrganizationPlan(plan)
    elif is_revoked:
        org.plan = OrganizationPlan.solo

    await db.flush()
    return {
        "handled": True,
        "organization_id": str(org.id),
        "subscription_status": status_str,
        "plan": org.plan.value,
    }


async def handle_subscription_event(
    db: AsyncSession, event: Any
) -> dict[str, Any]:
    """Dispatch a verified subscription/invoice Stripe event.

    Routed here from :func:`app.payments.service.handle_event`. Every
    branch resolves the canonical subscription object and reconciles the
    org row, so out-of-order webhook delivery still converges.
    """
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        result = await _apply_subscription_to_org(db, obj)
        await db.commit()
        return result

    if event_type == "checkout.session.completed":
        session = _as_dict(obj)
        subscription_id = session.get("subscription")
        if not subscription_id:
            return {"handled": False, "reason": "no_subscription_on_session"}
        _require_configured()
        sub = stripe.Subscription.retrieve(subscription_id)
        result = await _apply_subscription_to_org(db, sub)
        await db.commit()
        return result

    if event_type in ("invoice.paid", "invoice.payment_failed"):
        invoice = _as_dict(obj)
        subscription_id = subscription_id_from_invoice(invoice)
        if not subscription_id:
            return {"handled": False, "reason": "no_subscription_on_invoice"}
        _require_configured()
        sub = stripe.Subscription.retrieve(subscription_id)
        result = await _apply_subscription_to_org(db, sub)
        await db.commit()
        return result

    return {
        "handled": False,
        "reason": "unhandled_subscription_event",
        "event_type": event_type,
    }

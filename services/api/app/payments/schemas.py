"""Request / response schemas for the /payments router."""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StripeConfigResponse(BaseModel):
    """Public-safe Stripe config the frontend needs to bootstrap Stripe.js."""

    publishable_key: str = Field(
        ...,
        description="Stripe publishable key — safe to ship to the browser.",
    )
    api_version: str


class CreateCheckoutSessionRequest(BaseModel):
    """Open a Stripe Checkout session for a validated case_draft."""

    case_draft_id: uuid.UUID
    platform: str = Field(
        ...,
        description="IP office the fee is paid to (EUIPO, WIPO, USPTO, UKIPO).",
    )


class CreateCheckoutSessionResponse(BaseModel):
    """Returned to the frontend after a Stripe Checkout session is opened."""

    payment_intent_id: uuid.UUID
    checkout_session_id: str
    checkout_url: str = Field(
        ...,
        description="Absolute URL the frontend must redirect the user to.",
    )
    amount: Decimal
    currency: str
    expires_at: int = Field(
        ...,
        description="Unix epoch seconds; Stripe Checkout sessions expire after 24h.",
    )


class CreateUkipoCheckoutSessionRequest(BaseModel):
    """Open a Stripe Checkout session for a UKIPO ``awaiting_payment`` submission."""

    submission_id: uuid.UUID


class CreateUkipoCheckoutSessionResponse(BaseModel):
    """Returned to the frontend after a UKIPO Stripe Checkout session is opened."""

    submission_id: uuid.UUID
    checkout_session_id: str
    checkout_url: str
    amount_minor: int = Field(
        ...,
        description="Charge amount in Stripe minor units (pence for GBP).",
    )
    currency: str


class SubscriptionPlanOption(BaseModel):
    """One configured plan/interval with its live Stripe price."""

    plan: str = Field(..., description="Entitlement tier (solo, team, ...).")
    interval: str = Field(..., description="Billing interval (monthly, annual).")
    price_id: str
    unit_amount: int | None = Field(
        default=None,
        description="Amount in Stripe minor units (cents); null if metered.",
    )
    currency: str | None = None
    recurring_interval: str | None = Field(
        default=None, description="Stripe recurring interval (month, year)."
    )
    recurring_interval_count: int | None = None


class SubscriptionPlansResponse(BaseModel):
    plans: list[SubscriptionPlanOption]


class CreateSubscriptionCheckoutRequest(BaseModel):
    """Open a Stripe subscription Checkout session for an organization."""

    plan: str = Field(..., description="Entitlement tier (solo, team).")
    interval: str = Field(
        default="monthly", description="Billing interval (monthly, annual)."
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        description="Org to subscribe; defaults to the caller's default org.",
    )


class CreateSubscriptionCheckoutResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str


class BillingPortalRequest(BaseModel):
    organization_id: uuid.UUID | None = Field(
        default=None,
        description="Org to manage; defaults to the caller's default org.",
    )


class BillingPortalResponse(BaseModel):
    portal_url: str


class OrganizationSubscriptionResponse(BaseModel):
    """Current subscription state of an organization."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    plan: str
    subscription_status: str | None = None
    subscription_price_id: str | None = None
    subscription_current_period_end: str | None = None
    subscription_cancel_at_period_end: bool = False
    has_billing_account: bool = Field(
        ..., description="True once a Stripe customer exists for the org."
    )
    can_manage: bool = Field(
        ...,
        description="True if the caller may subscribe/manage billing "
        "(org owner/admin or system admin).",
    )


class PaymentIntentResponse(BaseModel):
    """Read view of a PaymentIntent row — used by /payments/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_draft_id: uuid.UUID
    payment_type: str
    provider: str
    amount: Decimal
    currency: str
    status: str
    gateway_payment_id: str | None


class RefundPaymentIntentRequest(BaseModel):
    """Operator-supplied reason text for an admin refund."""

    reason: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Audit reason persisted on the intent metadata.",
    )


class CaseDraftPaymentStatusResponse(BaseModel):
    """Aggregate payment status across all PaymentIntents for a draft.

    Used by the chat UI so a stale tool_result snapshot (intent_status
    captured at creation time) does not keep prompting the user to pay
    after a separate provider — e.g. Stripe — has already settled.
    """

    case_draft_id: uuid.UUID
    draft_status: str
    paid: bool = Field(
        ...,
        description="True if any PaymentIntent for this draft has reached 'confirmed'.",
    )
    pending: bool = Field(
        ...,
        description="True if any PaymentIntent is still 'created' or 'awaiting'.",
    )
    confirmed_intent_id: uuid.UUID | None = None
    confirmed_provider: str | None = None
    confirmed_amount: Decimal | None = None
    confirmed_currency: str | None = None
    # Auto-triggered submission state — populated by the Stripe
    # auto-submit hook on PaymentIntent.gateway_metadata.
    filing_attempt_id: uuid.UUID | None = None
    filing_status: str | None = None
    filing_external_reference: str | None = Field(
        default=None,
        description="EUIPO application number once the submission lands.",
    )
    filing_error: str | None = None
    # Compliance + NFT state (Stripe lane only — x402 lane uses the
    # legacy NftClaimPanel data feed via the UKIPO submission progress).
    compliance_artifact_id: uuid.UUID | None = None
    compliance_status: str | None = None
    compliance_onchain_tx: str | None = None
    case_id: uuid.UUID | None = Field(
        default=None,
        description="Promoted case row id once M5 fires; lets the chat UI "
        "render the existing NftClaimPanel for Stripe-paid filings.",
    )
    case_number: str | None = Field(
        default=None,
        description="Human-friendly case number that pairs with case_id; "
        "NftClaimPanel surfaces it next to the mint state.",
    )

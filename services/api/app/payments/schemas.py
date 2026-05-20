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

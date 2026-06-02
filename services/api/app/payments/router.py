"""FastAPI endpoints for Stripe payments.

- ``GET  /payments/stripe/config``   — publishable key + api version (public).
- ``POST /payments/stripe/checkout-session`` — open a session for a draft (auth).
- ``POST /payments/stripe/webhook``   — Stripe-signed event receiver (public).
- ``GET  /payments/{payment_intent_id}`` — read current PaymentIntent status (auth).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import CaseDraft, PaymentIntent, PaymentIntentStatus
from app.cases.models import Case
from app.auth.dependencies import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationMembershipRole,
)
from app.payments import service as stripe_service
from app.payments import subscription_service
from app.payments.schemas import (
    BillingPortalRequest,
    BillingPortalResponse,
    CaseDraftPaymentStatusResponse,
    CreateCheckoutSessionRequest,
    CreateCheckoutSessionResponse,
    CreateSubscriptionCheckoutRequest,
    CreateSubscriptionCheckoutResponse,
    CreateUkipoCheckoutSessionRequest,
    CreateUkipoCheckoutSessionResponse,
    OrganizationSubscriptionResponse,
    PaymentIntentResponse,
    RefundPaymentIntentRequest,
    StripeConfigResponse,
    SubscriptionPlanOption,
    SubscriptionPlansResponse,
)
from app.payments.service import StripeServiceError
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/stripe/config", response_model=StripeConfigResponse)
async def stripe_config() -> StripeConfigResponse:
    """Return the publishable key + pinned API version for the frontend.

    Fails closed if Stripe is not configured so the frontend hides the
    card-payment option instead of rendering with a missing key.
    """
    if not settings.stripe_publishable_key or not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured on this server.",
        )
    return StripeConfigResponse(
        publishable_key=settings.stripe_publishable_key,
        api_version=settings.stripe_api_version,
    )


@router.post(
    "/stripe/checkout-session",
    response_model=CreateCheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_checkout_session(
    body: CreateCheckoutSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CreateCheckoutSessionResponse:
    """Open a Stripe Checkout session for a validated case_draft.

    Idempotent on ``(case_draft_id, platform)`` — re-calling returns the
    same session URL if it is still open, otherwise opens a fresh one.
    """
    try:
        intent, session = await stripe_service.create_checkout_session(
            db,
            user=current_user,
            case_draft_id=body.case_draft_id,
            platform=body.platform,
        )
    except StripeServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if not session.url:
        # Stripe is contractually obliged to return a URL for mode=payment
        # checkout sessions; surfacing a clear error is friendlier than
        # letting the frontend redirect to None.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe returned a session without a redirect URL.",
        )

    return CreateCheckoutSessionResponse(
        payment_intent_id=intent.id,
        checkout_session_id=session.id,
        checkout_url=session.url,
        amount=intent.amount,
        currency=intent.currency,
        expires_at=session.expires_at,
    )


@router.post(
    "/stripe/ukipo-checkout-session",
    response_model=CreateUkipoCheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ukipo_checkout_session_endpoint(
    body: CreateUkipoCheckoutSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CreateUkipoCheckoutSessionResponse:
    """Open a Stripe Checkout session for a UKIPO submission.

    Parallel to the EUIPO ``/stripe/checkout-session`` endpoint but
    keyed by ``submission_id`` instead of ``case_draft_id`` — UKIPO
    filings have their own lifecycle around the robot.
    """
    try:
        url, session_id_value, unit_amount = await (
            stripe_service.create_ukipo_checkout_session(
                db,
                user=current_user,
                submission_id=body.submission_id,
            )
        )
    except StripeServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return CreateUkipoCheckoutSessionResponse(
        submission_id=body.submission_id,
        checkout_session_id=session_id_value,
        checkout_url=url,
        amount_minor=unit_amount,
        currency="GBP",
    )


@router.get(
    "/stripe/sessions/{session_id}/status",
    response_model=PaymentIntentResponse,
)
async def reconcile_stripe_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaymentIntentResponse:
    """Reconcile a Checkout session from Stripe and return the latest intent.

    Used by the success page so the UI can confirm payment without
    waiting for the webhook (which may be delayed or unconfigured).
    Safe under racing — webhook + this endpoint converge on the same
    terminal status.
    """
    try:
        intent = await stripe_service.reconcile_session(
            db, session_id, user=current_user
        )
    except StripeServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return PaymentIntentResponse(
        id=intent.id,
        case_draft_id=intent.case_draft_id,
        payment_type=intent.payment_type.value,
        provider=intent.provider.value,
        amount=intent.amount,
        currency=intent.currency,
        status=intent.status.value,
        gateway_payment_id=intent.gateway_payment_id,
    )


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a Stripe-signed event and advance the PaymentIntent state.

    The raw body is required for signature verification — do NOT parse
    JSON before calling ``verify_webhook``.
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header.",
        )
    payload = await request.body()

    try:
        event = stripe_service.verify_webhook(payload, stripe_signature)
    except StripeServiceError as exc:
        # 400 (not 401) is the Stripe-recommended response for a bad
        # signature — Stripe will retry until the secret matches.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    try:
        result = await stripe_service.handle_event(db, event)
    except Exception as exc:  # noqa: BLE001
        # stripe.Event supports __getitem__ but not .get() — use
        # subscript access so the logger itself does not blow up and
        # swallow the real exception trace.
        try:
            event_id = event["id"]
            event_type = event["type"]
        except (KeyError, TypeError):
            event_id = "<unknown>"
            event_type = "<unknown>"
        logger.exception("Stripe event handler failed for %s", event_id)
        # Capture into Sentry with structured context so the dashboard
        # groups failing webhook events by type rather than treating
        # them as random 500s.
        from app.observability import capture_exception as _capture

        _capture(
            exc,
            stripe_event_id=event_id,
            stripe_event_type=event_type,
        )
        # Return 500 so Stripe retries — never silently swallow failures
        # that could leave a PaymentIntent stuck in 'awaiting' forever.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook handler failed; Stripe will retry.",
        )

    return {"received": True, "event_type": event["type"], **result}


# ---------------------------------------------------------------------------
# Subscriptions (recurring billing — issue #62)
# ---------------------------------------------------------------------------


async def _resolve_billing_org(
    db: AsyncSession,
    user: User,
    organization_id: uuid.UUID | None,
    *,
    require_manage: bool,
) -> tuple[Organization, bool]:
    """Resolve the org for a billing call and the caller's manage rights.

    Defaults to the caller's ``default_organization_id`` when no org is
    given. Any member (or system admin) may *read* billing state;
    ``require_manage=True`` additionally enforces owner/admin (or system
    admin) for state-changing calls (checkout, portal). Returns the org
    plus a ``can_manage`` flag the read path surfaces to the UI.
    """
    org_id = organization_id or user.default_organization_id
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No organization selected and you have no default org.",
        )
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    if user.role == UserRole.admin:
        return org, True

    membership = (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org.id,
                OrganizationMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization.",
        )
    can_manage = membership.role in (
        OrganizationMembershipRole.owner,
        OrganizationMembershipRole.admin,
    )
    if require_manage and not can_manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an organization owner or admin can manage billing.",
        )
    return org, can_manage


@router.get(
    "/stripe/subscription/plans",
    response_model=SubscriptionPlansResponse,
)
async def list_subscription_plans(
    _: User = Depends(get_current_user),
) -> SubscriptionPlansResponse:
    """List configured subscription plans with live Stripe prices.

    Amounts come straight from Stripe, so the pricing UI never hardcodes
    a number. Returns an empty list when Stripe is unconfigured.
    """
    if not settings.stripe_secret_key:
        return SubscriptionPlansResponse(plans=[])
    try:
        plans = subscription_service.list_available_plans()
    except StripeServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return SubscriptionPlansResponse(
        plans=[SubscriptionPlanOption(**p) for p in plans]
    )


@router.get(
    "/stripe/subscription/status",
    response_model=OrganizationSubscriptionResponse,
)
async def get_subscription_status(
    organization_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrganizationSubscriptionResponse:
    """Current subscription state for any org the caller belongs to."""
    org, can_manage = await _resolve_billing_org(
        db, current_user, organization_id, require_manage=False
    )
    return OrganizationSubscriptionResponse(
        organization_id=org.id,
        plan=org.plan.value,
        subscription_status=org.subscription_status,
        subscription_price_id=org.subscription_price_id,
        subscription_current_period_end=(
            org.subscription_current_period_end.isoformat()
            if org.subscription_current_period_end
            else None
        ),
        subscription_cancel_at_period_end=(
            org.subscription_cancel_at_period_end
        ),
        has_billing_account=org.stripe_customer_id is not None,
        can_manage=can_manage,
    )


@router.post(
    "/stripe/subscription/checkout-session",
    response_model=CreateSubscriptionCheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription_checkout_session(
    body: CreateSubscriptionCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CreateSubscriptionCheckoutResponse:
    """Open a Stripe subscription Checkout session (Stripe Tax + VAT id)."""
    org, _ = await _resolve_billing_org(
        db, current_user, body.organization_id, require_manage=True
    )
    try:
        session = await subscription_service.create_subscription_checkout(
            db,
            org=org,
            user=current_user,
            plan=body.plan,
            interval=body.interval,
        )
    except StripeServiceError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail=exc.user_message
        )
    if not session.url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe returned a session without a redirect URL.",
        )
    return CreateSubscriptionCheckoutResponse(
        checkout_session_id=session.id,
        checkout_url=session.url,
    )


@router.post(
    "/stripe/subscription/portal",
    response_model=BillingPortalResponse,
)
async def create_billing_portal(
    body: BillingPortalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillingPortalResponse:
    """Open a Stripe Billing Portal session for self-service management."""
    org, _ = await _resolve_billing_org(
        db, current_user, body.organization_id, require_manage=True
    )
    try:
        session = await subscription_service.create_billing_portal_session(
            org=org
        )
    except StripeServiceError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail=exc.user_message
        )
    return BillingPortalResponse(portal_url=session.url)


@router.get(
    "/case-drafts/{case_draft_id}/status",
    response_model=CaseDraftPaymentStatusResponse,
)
async def case_draft_payment_status(
    case_draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseDraftPaymentStatusResponse:
    """Aggregate payment state across every PaymentIntent on a draft.

    The chat UI calls this when rendering a prepare_payment tool result
    so a stale tool_result snapshot does not keep prompting the user to
    pay after a separate provider (Stripe vs. x402) has settled. Refuses
    with 404 when the draft does not belong to the authenticated user.
    """
    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    intents = (
        await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.case_draft_id == case_draft_id
            )
        )
    ).scalars().all()

    confirmed = next(
        (i for i in intents if i.status == PaymentIntentStatus.confirmed),
        None,
    )
    pending = any(
        i.status in (PaymentIntentStatus.created, PaymentIntentStatus.awaiting)
        for i in intents
    )

    # Pull the auto-submitted filing reference + compliance/NFT state
    # off the confirmed intent's gateway_metadata.
    confirmed_meta = (confirmed.gateway_metadata or {}) if confirmed else {}

    def _safe_uuid(value: object) -> uuid.UUID | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return uuid.UUID(value)
        except (TypeError, ValueError):
            return None

    # Resolve case_number for the chat UI so it can render the
    # NftClaimPanel without a follow-up /cases/{id} round trip.
    case_id = _safe_uuid(confirmed_meta.get("case_id")) if confirmed_meta else None
    case_number: str | None = None
    if case_id is not None:
        case_row = (
            await db.execute(select(Case).where(Case.id == case_id))
        ).scalar_one_or_none()
        if case_row is not None:
            case_number = case_row.case_number

    return CaseDraftPaymentStatusResponse(
        case_draft_id=draft.id,
        draft_status=draft.status.value,
        paid=confirmed is not None,
        pending=pending and confirmed is None,
        confirmed_intent_id=confirmed.id if confirmed else None,
        confirmed_provider=confirmed.provider.value if confirmed else None,
        confirmed_amount=confirmed.amount if confirmed else None,
        confirmed_currency=confirmed.currency if confirmed else None,
        filing_attempt_id=_safe_uuid(confirmed_meta.get("filing_attempt_id")),
        filing_status=confirmed_meta.get("filing_status"),
        filing_external_reference=confirmed_meta.get(
            "filing_external_reference"
        ),
        filing_error=confirmed_meta.get("filing_error"),
        compliance_artifact_id=_safe_uuid(
            confirmed_meta.get("compliance_artifact_id")
        ),
        compliance_status=confirmed_meta.get("compliance_status"),
        compliance_onchain_tx=confirmed_meta.get("compliance_onchain_tx"),
        case_id=case_id,
        case_number=case_number,
    )


@router.post(
    "/{payment_intent_id}/refund",
    response_model=PaymentIntentResponse,
)
async def refund_payment_intent_endpoint(
    payment_intent_id: uuid.UUID,
    body: RefundPaymentIntentRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
) -> PaymentIntentResponse:
    """Issue a Stripe refund for a confirmed PaymentIntent.

    Admin-only — refunds move real money and write to Stripe, so we
    require the ``admin`` role rather than the requesting user. The
    auto-submit hook fires the same ``refund_payment_intent`` service
    automatically when EUIPO rejects a submission permanently; this
    endpoint covers the operator-discretion path (a customer
    complaint, a fraud signal, a manual reconciliation).
    """
    intent = (
        await db.execute(
            select(PaymentIntent).where(PaymentIntent.id == payment_intent_id)
        )
    ).scalar_one_or_none()
    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    intent = await stripe_service.refund_payment_intent(
        db, intent, reason=body.reason, initiated_by="operator"
    )
    return PaymentIntentResponse(
        id=intent.id,
        case_draft_id=intent.case_draft_id,
        payment_type=intent.payment_type.value,
        provider=intent.provider.value,
        amount=intent.amount,
        currency=intent.currency,
        status=intent.status.value,
        gateway_payment_id=intent.gateway_payment_id,
    )


@router.get(
    "/{payment_intent_id}",
    response_model=PaymentIntentResponse,
)
async def read_payment_intent(
    payment_intent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaymentIntentResponse:
    """Read a PaymentIntent the authenticated user owns.

    Ownership is enforced via the draft's user_id — refuse 404 (not 403)
    when a user asks about somebody else's intent so the existence of
    the row does not leak.
    """
    intent = (
        await db.execute(
            select(PaymentIntent).where(PaymentIntent.id == payment_intent_id)
        )
    ).scalar_one_or_none()
    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == intent.case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return PaymentIntentResponse(
        id=intent.id,
        case_draft_id=intent.case_draft_id,
        payment_type=intent.payment_type.value,
        provider=intent.provider.value,
        amount=intent.amount,
        currency=intent.currency,
        status=intent.status.value,
        gateway_payment_id=intent.gateway_payment_id,
    )

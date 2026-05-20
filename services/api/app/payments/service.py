"""Stripe integration service layer.

Owns the conversion between our domain (Decimal amounts in ISO currency
codes) and Stripe's wire format (integer minor units), plus the
state-machine mapping between Stripe events and ``PaymentIntent`` rows.

All money handling goes through this module — never call ``stripe.*``
directly from a router or tool.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.filing_service import (
    FilingServiceError,
    find_submitted_attempt,
    submit_eutm,
)
from app.agent.models import (
    CaseDraft,
    CaseDraftStatus,
    FilingPlatform,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentProvider,
    PaymentType,
)
from app.agent.tools.quote_fees import _quote_euipo_trademark
from app.compliance.service import (
    ComplianceProofError,
    generate_for_payment_intent,
    promote_draft_and_setup_nft,
    submit_onchain_attestation,
)
from app.config import settings
from app.users.models import User

logger = logging.getLogger(__name__)


class StripeServiceError(RuntimeError):
    """Domain-level Stripe failure that should surface to the caller."""


# ---------------------------------------------------------------------------
# Currency / amount conversion
# ---------------------------------------------------------------------------

# ISO 4217 codes that Stripe treats as zero-decimal (no minor unit).
# We do not currently quote in any of these, but the conversion must
# remain correct if WIPO/JPO adapters land later. List sourced from
# https://docs.stripe.com/currencies#zero-decimal
_ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg",
        "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
)


def _to_minor_units(amount: Decimal, currency: str) -> int:
    """Convert a Decimal currency amount into Stripe's integer minor unit.

    Stripe expects amounts in the smallest unit (cents for USD, Rappen
    for CHF, etc.). Zero-decimal currencies are passed as-is.
    """
    if amount < 0:
        raise StripeServiceError(f"Negative amount not allowed: {amount}")
    code = currency.lower()
    if code in _ZERO_DECIMAL_CURRENCIES:
        # No subdivision — must be an integer already.
        if amount % 1 != 0:
            raise StripeServiceError(
                f"{currency} is zero-decimal; cannot quote a fractional "
                f"amount ({amount})."
            )
        return int(amount)
    # Multiply by 100 and round HALF_UP (Stripe rejects fractional minor
    # units). We round here defensively even though our fee schedules
    # are sourced as integer EUR — a future schedule with cents would
    # otherwise silently truncate.
    cents = int((amount * 100).to_integral_value(rounding="ROUND_HALF_UP"))
    return cents


# ---------------------------------------------------------------------------
# SDK bootstrap
# ---------------------------------------------------------------------------


def _require_configured() -> None:
    if not settings.stripe_secret_key:
        raise StripeServiceError(
            "Stripe is not configured on this server "
            "(STRIPE_SECRET_KEY is empty)."
        )
    # SDK reads `stripe.api_key` from module-level; set on every call so
    # config rotation via reload picks up.
    stripe.api_key = settings.stripe_secret_key
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version


# ---------------------------------------------------------------------------
# Fee resolution
# ---------------------------------------------------------------------------


def _resolve_fee(platform: str, nice_classes: list[int]) -> dict[str, Any]:
    """Return ``{amount, currency, breakdown, source, last_verified}``.

    Only EUIPO is wired today — same source of truth as the agent's
    ``prepare_payment`` tool. Other platforms raise so Stripe never
    charges a guessed amount.
    """
    if platform == "EUIPO":
        quote = _quote_euipo_trademark(nice_classes)
        return {
            "amount": Decimal(quote["total"]),
            "currency": quote["currency"],
            "breakdown": quote["breakdown"],
            "source": quote["source"],
            "last_verified": quote["schedule_last_verified"],
        }
    raise StripeServiceError(
        f"Fee schedule for {platform} is not wired yet — cannot create a "
        "Stripe Checkout session."
    )


# ---------------------------------------------------------------------------
# Checkout session
# ---------------------------------------------------------------------------


async def create_checkout_session(
    db: AsyncSession,
    *,
    user: User,
    case_draft_id: uuid.UUID,
    platform: str,
) -> tuple[PaymentIntent, stripe.checkout.Session]:
    """Open a Stripe Checkout session for a validated draft.

    Returns the persisted ``PaymentIntent`` and the live Stripe session
    object so the router can surface ``session.url`` to the frontend.

    Idempotent: a second call for the same draft+platform returns the
    same ``PaymentIntent`` row (and re-uses the Stripe session if it is
    still open, otherwise creates a fresh one).
    """
    _require_configured()

    draft = (
        await db.execute(select(CaseDraft).where(CaseDraft.id == case_draft_id))
    ).scalar_one_or_none()
    if draft is None:
        raise StripeServiceError(f"No case_draft found with id {case_draft_id}.")
    if draft.user_id != user.id:
        raise StripeServiceError(
            "case_draft does not belong to the authenticated user."
        )
    if draft.status not in (
        CaseDraftStatus.validated,
        CaseDraftStatus.awaiting_payment,
    ):
        raise StripeServiceError(
            f"case_draft.status is '{draft.status.value}'; payment can only "
            "be prepared once the draft has been validated."
        )

    nice_classes = [int(c) for c in (draft.nice_classes or [])]
    fee = _resolve_fee(platform, nice_classes)
    amount = fee["amount"]
    currency = fee["currency"]
    unit_amount = _to_minor_units(amount, currency)

    idempotency_key = (
        f"draft:{draft.id}:platform_fee:{platform}:stripe"
    )

    existing = (
        await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()

    intent: PaymentIntent
    if existing is None:
        intent = PaymentIntent(
            case_draft_id=draft.id,
            payment_type=PaymentType.platform_fee,
            provider=PaymentProvider.stripe,
            amount=amount,
            currency=currency,
            status=PaymentIntentStatus.created,
            idempotency_key=idempotency_key,
            gateway_metadata={
                "platform": platform,
                "fee_breakdown": fee["breakdown"],
                "fee_source": fee["source"],
                "fee_last_verified": fee["last_verified"],
            },
        )
        db.add(intent)
        await db.flush()  # surface intent.id for the Stripe metadata
    else:
        intent = existing

    # If we already have a session that's still open, re-use it.
    existing_session_id = (intent.gateway_metadata or {}).get(
        "stripe_session_id"
    )
    if existing_session_id and intent.status == PaymentIntentStatus.created:
        try:
            existing_session = stripe.checkout.Session.retrieve(
                existing_session_id
            )
        except stripe.StripeError as exc:  # noqa: BLE001
            logger.warning(
                "Failed to retrieve existing Stripe session %s: %s",
                existing_session_id,
                exc,
            )
            existing_session = None
        if existing_session is not None and existing_session.status == "open":
            await db.commit()
            return intent, existing_session

    product_name = _product_name(draft, platform)
    description = _product_description(draft, fee)

    session_kwargs: dict[str, Any] = {
        "mode": "payment",
        "payment_method_types": ["card"],
        "line_items": [
            {
                "price_data": {
                    "currency": currency.lower(),
                    "unit_amount": unit_amount,
                    "product_data": {
                        "name": product_name,
                        "description": description,
                    },
                },
                "quantity": 1,
            }
        ],
        "success_url": settings.stripe_success_url,
        "cancel_url": settings.stripe_cancel_url,
        "client_reference_id": str(intent.id),
        "metadata": {
            "payment_intent_id": str(intent.id),
            "case_draft_id": str(draft.id),
            "platform": platform,
            "user_id": str(user.id),
        },
        "payment_intent_data": {
            "metadata": {
                "payment_intent_id": str(intent.id),
                "case_draft_id": str(draft.id),
            }
        },
    }
    if user.email:
        session_kwargs["customer_email"] = user.email

    try:
        session = stripe.checkout.Session.create(
            **session_kwargs,
            idempotency_key=idempotency_key,
        )
    except stripe.StripeError as exc:  # noqa: BLE001
        logger.exception("Stripe checkout.Session.create failed")
        raise StripeServiceError(f"Stripe rejected the session: {exc}") from exc

    metadata = dict(intent.gateway_metadata or {})
    metadata["stripe_session_id"] = session.id
    metadata["stripe_payment_intent_id"] = session.payment_intent
    metadata["checkout_url"] = session.url
    intent.gateway_metadata = metadata
    intent.gateway_payment_id = session.payment_intent or session.id
    intent.status = PaymentIntentStatus.awaiting

    draft.status = CaseDraftStatus.awaiting_payment

    await db.commit()
    await db.refresh(intent)
    return intent, session


def _product_name(draft: CaseDraft, platform: str) -> str:
    mark = draft.mark_text or "Unnamed mark"
    return f"{platform} trademark filing — “{mark}”"


def _product_description(draft: CaseDraft, fee: dict[str, Any]) -> str:
    nice = ", ".join(str(c) for c in (draft.nice_classes or []))
    classes_part = f"Nice classes: {nice}." if nice else ""
    source_part = f"Fee source: {fee['source']} ({fee['last_verified']})."
    return " ".join(p for p in (classes_part, source_part) if p)


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------


def verify_webhook(payload: bytes, signature: str) -> stripe.Event:
    """Verify the Stripe-Signature header against the raw request body.

    Returns the parsed event. Raises ``StripeServiceError`` on any
    mismatch — the router translates that to a 400.
    """
    _require_configured()
    if not settings.stripe_webhook_secret:
        raise StripeServiceError(
            "STRIPE_WEBHOOK_SECRET is not configured; refusing to process "
            "webhook events (fail-closed)."
        )
    try:
        return stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=settings.stripe_webhook_secret,
        )
    except ValueError as exc:
        raise StripeServiceError(f"Invalid webhook payload: {exc}") from exc
    except stripe.SignatureVerificationError as exc:
        raise StripeServiceError(
            f"Stripe signature verification failed: {exc}"
        ) from exc


_TERMINAL_STATUSES = {
    PaymentIntentStatus.confirmed,
    PaymentIntentStatus.refunded,
    PaymentIntentStatus.failed,
    PaymentIntentStatus.expired,
}


# Platforms whose submission can be auto-fired the moment Stripe
# confirms the fee payment. EUIPO is the only adapter wired today.
# UKIPO ships via the start_ukipo_filing robot, which has its own
# (different) payment binding — we do NOT auto-trigger it from here.
_AUTO_SUBMIT_PLATFORMS = {"EUIPO": FilingPlatform.EUIPO}


async def _auto_submit_after_confirmation(
    db: AsyncSession, intent: PaymentIntent, draft: CaseDraft
) -> None:
    """Trigger the EUIPO submission as soon as the payment confirms.

    Runs from BOTH the webhook handler and the success-url reconciler;
    whichever fires first wins. Idempotent against duplicates because
    ``find_submitted_attempt`` short-circuits when a prior attempt
    already succeeded.

    Submission errors are persisted on the FilingAttempt row but do
    NOT propagate — the payment stays confirmed and a human can retry
    via the ``submit_filing`` agent tool. We never want a flaky EUIPO
    sandbox to flip the payment back to a non-terminal state.
    """
    platform_label = (intent.gateway_metadata or {}).get("platform")
    if platform_label not in _AUTO_SUBMIT_PLATFORMS:
        return

    platform = _AUTO_SUBMIT_PLATFORMS[platform_label]
    existing = await find_submitted_attempt(
        db, case_draft_id=draft.id, platform=platform
    )
    if existing is not None:
        # Stamp the metadata so the chat UI can surface the existing
        # external_reference even if it lands here via a reconcile poll
        # rather than the webhook.
        metadata = dict(intent.gateway_metadata or {})
        metadata["filing_attempt_id"] = str(existing.id)
        metadata["filing_external_reference"] = existing.external_reference
        metadata["filing_status"] = existing.status.value
        intent.gateway_metadata = metadata
        return

    try:
        outcome = await submit_eutm(db, draft, initiated_by="stripe_auto")
    except FilingServiceError as exc:
        logger.warning(
            "EUIPO auto-submit pre-flight failed for draft %s: %s",
            draft.id,
            exc,
        )
        return

    metadata = dict(intent.gateway_metadata or {})
    metadata["filing_attempt_id"] = outcome.get("filing_attempt_id")
    metadata["filing_status"] = outcome.get("status")
    if outcome.get("ok"):
        metadata["filing_external_reference"] = outcome.get("external_reference")
        logger.info(
            "EUIPO auto-submit OK draft=%s attempt=%s ref=%s",
            draft.id,
            outcome.get("filing_attempt_id"),
            outcome.get("external_reference"),
        )
    else:
        metadata["filing_error"] = outcome.get("error")
        logger.warning(
            "EUIPO auto-submit FAIL draft=%s attempt=%s err=%s",
            draft.id,
            outcome.get("filing_attempt_id"),
            outcome.get("error"),
        )
    intent.gateway_metadata = metadata

    # Generate the compliance artifact regardless of EUIPO outcome.
    # The proof binds the Stripe payment to the filing context — it
    # is independent of whether EUIPO has accepted the submission
    # yet. M4 picks the artifact up and broadcasts the on-chain
    # verifier transaction.
    await _generate_compliance_after_confirmation(db, intent, draft)


async def _generate_compliance_after_confirmation(
    db: AsyncSession, intent: PaymentIntent, draft: CaseDraft
) -> None:
    """Drive the Stripe-lane compliance proof generator + persist.

    Errors are absorbed onto the artifact row + intent metadata so a
    flaky local Node prover does not unwind the confirmed payment.
    """
    try:
        artifact = await generate_for_payment_intent(db, intent, draft)
    except ComplianceProofError as exc:
        logger.warning(
            "Compliance proof generation failed for intent %s: %s",
            intent.id,
            exc,
        )
        metadata = dict(intent.gateway_metadata or {})
        metadata["compliance_status"] = "failed"
        metadata["compliance_error"] = str(exc)
        intent.gateway_metadata = metadata
        return

    metadata = dict(intent.gateway_metadata or {})
    metadata["compliance_artifact_id"] = str(artifact.id)
    metadata["compliance_status"] = artifact.status
    metadata["compliance_query_hash_hex"] = artifact.query_hash.hex()
    if artifact.error:
        metadata["compliance_error"] = artifact.error
    else:
        metadata.pop("compliance_error", None)
    intent.gateway_metadata = metadata
    logger.info(
        "Compliance artifact intent=%s artifact=%s status=%s",
        intent.id,
        artifact.id,
        artifact.status,
    )

    # M4 — broadcast the on-chain verify_compliance_proof tx as soon
    # as the artifact is generated. Failures stay on the artifact row
    # (status=failed) and surface via the agg-status endpoint; the
    # confirmed payment is never reverted.
    if artifact.status == "created":
        try:
            artifact = await submit_onchain_attestation(db, artifact, draft)
        except ComplianceProofError as exc:
            logger.warning(
                "On-chain attestation failed for artifact %s: %s",
                artifact.id,
                exc,
            )
            metadata = dict(intent.gateway_metadata or {})
            metadata["compliance_onchain_error"] = str(exc)
            intent.gateway_metadata = metadata
            return
        metadata = dict(intent.gateway_metadata or {})
        metadata["compliance_status"] = artifact.status
        if artifact.onchain_tx:
            metadata["compliance_onchain_tx"] = artifact.onchain_tx
        intent.gateway_metadata = metadata
        logger.info(
            "On-chain compliance attestation OK artifact=%s tx=%s",
            artifact.id,
            artifact.onchain_tx,
        )

        # M5 — promote draft into cases + schedule the Token-2022 mint
        # setup. Synchronous part (case row creation) is small; the
        # NFT setup itself runs as a background task and lands on the
        # case row when ready. NftClaimPanel can already see the case
        # before the mint exists.
        try:
            case_id = await promote_draft_and_setup_nft(db, draft)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Case promotion / NFT setup failed for draft %s: %s",
                draft.id,
                exc,
            )
            metadata = dict(intent.gateway_metadata or {})
            metadata["case_promotion_error"] = str(exc)
            intent.gateway_metadata = metadata
            return

        if case_id is not None:
            metadata = dict(intent.gateway_metadata or {})
            metadata["case_id"] = str(case_id)
            intent.gateway_metadata = metadata


async def handle_event(db: AsyncSession, event: stripe.Event) -> dict[str, Any]:
    """Dispatch a verified Stripe event to its handler.

    Idempotent: re-delivering the same event (Stripe retries up to 3
    days) on an already-terminal PaymentIntent is a no-op. Unknown
    event types are logged and ignored — Stripe sends many events we
    do not care about.
    """
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        return await _handle_session_completed(db, obj)
    if event_type == "checkout.session.expired":
        return await _handle_session_expired(db, obj)
    if event_type == "checkout.session.async_payment_failed":
        return await _handle_session_failed(db, obj)
    if event_type == "payment_intent.payment_failed":
        return await _handle_payment_intent_failed(db, obj)
    if event_type == "charge.refunded":
        return await _handle_charge_refunded(db, obj)

    logger.debug("Ignoring Stripe event type %s", event_type)
    return {"ignored": True, "event_type": event_type}


async def _lookup_intent_by_session(
    db: AsyncSession, session: dict[str, Any]
) -> PaymentIntent | None:
    """Find our PaymentIntent row from a Stripe Checkout session payload.

    Falls back through the strongest correlation signals: client
    reference id (which we set to our intent.id), metadata, then the
    embedded stripe payment_intent id.
    """
    ref = session.get("client_reference_id")
    if ref:
        try:
            pid = uuid.UUID(ref)
        except (TypeError, ValueError):
            pid = None
        if pid is not None:
            row = (
                await db.execute(
                    select(PaymentIntent).where(PaymentIntent.id == pid)
                )
            ).scalar_one_or_none()
            if row is not None:
                return row

    meta_id = (session.get("metadata") or {}).get("payment_intent_id")
    if meta_id:
        try:
            pid = uuid.UUID(meta_id)
        except (TypeError, ValueError):
            pid = None
        if pid is not None:
            row = (
                await db.execute(
                    select(PaymentIntent).where(PaymentIntent.id == pid)
                )
            ).scalar_one_or_none()
            if row is not None:
                return row

    stripe_pi = session.get("payment_intent")
    if stripe_pi:
        row = (
            await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.gateway_payment_id == stripe_pi
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row

    return None


async def _handle_session_completed(
    db: AsyncSession, session: dict[str, Any]
) -> dict[str, Any]:
    intent = await _lookup_intent_by_session(db, session)
    if intent is None:
        logger.warning(
            "checkout.session.completed received for unknown session %s",
            session.get("id"),
        )
        return {"handled": False, "reason": "intent_not_found"}

    if intent.status in _TERMINAL_STATUSES:
        return {"handled": False, "reason": "already_terminal"}

    payment_status = session.get("payment_status")
    if payment_status != "paid":
        # `checkout.session.completed` also fires for delayed-payment
        # methods (e.g. SEPA pending). Leave the intent in 'awaiting'
        # and wait for the matching payment_intent.succeeded event.
        logger.info(
            "Session %s completed in payment_status=%s — waiting for "
            "follow-up event.",
            session.get("id"),
            payment_status,
        )
        return {
            "handled": True,
            "status": "pending_async_payment",
            "payment_status": payment_status,
        }

    intent.status = PaymentIntentStatus.confirmed
    intent.confirmed_at = datetime.now(timezone.utc)
    stripe_pi = session.get("payment_intent")
    if stripe_pi:
        intent.gateway_payment_id = stripe_pi
    metadata = dict(intent.gateway_metadata or {})
    metadata["stripe_session_status"] = session.get("status")
    metadata["amount_total"] = session.get("amount_total")
    metadata["payment_status"] = payment_status
    intent.gateway_metadata = metadata

    # Advance the draft so subsequent submit_filing knows payment is done.
    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == intent.case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is not None and draft.status == CaseDraftStatus.awaiting_payment:
        draft.status = CaseDraftStatus.paid

    # Auto-trigger EUIPO submission in the same transaction. Errors are
    # absorbed onto the FilingAttempt row — we do not let a flaky
    # sandbox revert the confirmed payment.
    if draft is not None and draft.status == CaseDraftStatus.paid:
        await _auto_submit_after_confirmation(db, intent, draft)

    await db.commit()
    return {
        "handled": True,
        "payment_intent_id": str(intent.id),
        "status": intent.status.value,
        "filing_external_reference": (
            (intent.gateway_metadata or {}).get("filing_external_reference")
        ),
    }


async def _handle_session_expired(
    db: AsyncSession, session: dict[str, Any]
) -> dict[str, Any]:
    intent = await _lookup_intent_by_session(db, session)
    if intent is None or intent.status in _TERMINAL_STATUSES:
        return {"handled": False}
    intent.status = PaymentIntentStatus.expired
    await db.commit()
    return {"handled": True, "status": "expired"}


async def _handle_session_failed(
    db: AsyncSession, session: dict[str, Any]
) -> dict[str, Any]:
    intent = await _lookup_intent_by_session(db, session)
    if intent is None or intent.status in _TERMINAL_STATUSES:
        return {"handled": False}
    intent.status = PaymentIntentStatus.failed
    intent.failed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"handled": True, "status": "failed"}


async def _handle_payment_intent_failed(
    db: AsyncSession, payment_intent: dict[str, Any]
) -> dict[str, Any]:
    stripe_pi = payment_intent.get("id")
    if not stripe_pi:
        return {"handled": False}
    intent = (
        await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.gateway_payment_id == stripe_pi
            )
        )
    ).scalar_one_or_none()
    if intent is None or intent.status in _TERMINAL_STATUSES:
        return {"handled": False}
    intent.status = PaymentIntentStatus.failed
    intent.failed_at = datetime.now(timezone.utc)
    metadata = dict(intent.gateway_metadata or {})
    metadata["stripe_failure_code"] = payment_intent.get("last_payment_error", {}).get("code")
    metadata["stripe_failure_message"] = payment_intent.get("last_payment_error", {}).get("message")
    intent.gateway_metadata = metadata
    await db.commit()
    return {"handled": True, "status": "failed"}


async def reconcile_session(
    db: AsyncSession, session_id: str, *, user: User
) -> PaymentIntent:
    """Re-fetch a Checkout session from Stripe and reconcile our DB row.

    The success_url handler calls this so the UI does not have to wait
    for the webhook (which may be unconfigured in dev, or delayed under
    load). Idempotent against the webhook — whichever runs first wins
    via the ``_TERMINAL_STATUSES`` guard.

    Ownership: rejects if the resolved PaymentIntent does not belong to
    the authenticated user (404-style refusal via StripeServiceError).
    """
    _require_configured()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError as exc:  # noqa: BLE001
        raise StripeServiceError(f"Stripe rejected session lookup: {exc}") from exc

    intent = await _lookup_intent_by_session(db, session.to_dict())
    if intent is None:
        raise StripeServiceError(
            f"No payment_intent found for session {session_id}."
        )

    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == intent.case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is None or draft.user_id != user.id:
        raise StripeServiceError(
            "Session does not belong to the authenticated user."
        )

    if intent.status in _TERMINAL_STATUSES:
        return intent

    if session.payment_status == "paid":
        intent.status = PaymentIntentStatus.confirmed
        intent.confirmed_at = datetime.now(timezone.utc)
        if session.payment_intent:
            intent.gateway_payment_id = session.payment_intent
        metadata = dict(intent.gateway_metadata or {})
        metadata["stripe_session_status"] = session.status
        metadata["amount_total"] = session.amount_total
        metadata["payment_status"] = session.payment_status
        metadata["reconciled_via"] = "success_url"
        intent.gateway_metadata = metadata
        if draft.status == CaseDraftStatus.awaiting_payment:
            draft.status = CaseDraftStatus.paid
        # Auto-submit also runs from the success_url path so a missing
        # webhook does not block the filing from going out. Idempotent
        # against the webhook firing in parallel.
        if draft.status == CaseDraftStatus.paid:
            await _auto_submit_after_confirmation(db, intent, draft)
    elif session.status == "expired":
        intent.status = PaymentIntentStatus.expired

    await db.commit()
    await db.refresh(intent)
    return intent


async def _handle_charge_refunded(
    db: AsyncSession, charge: dict[str, Any]
) -> dict[str, Any]:
    stripe_pi = charge.get("payment_intent")
    if not stripe_pi:
        return {"handled": False}
    intent = (
        await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.gateway_payment_id == stripe_pi
            )
        )
    ).scalar_one_or_none()
    if intent is None:
        return {"handled": False}
    intent.status = PaymentIntentStatus.refunded
    metadata = dict(intent.gateway_metadata or {})
    metadata["refunded_amount"] = charge.get("amount_refunded")
    intent.gateway_metadata = metadata
    await db.commit()
    return {"handled": True, "status": "refunded"}

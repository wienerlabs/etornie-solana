"""Stripe integration service layer.

Owns the conversion between our domain (Decimal amounts in ISO currency
codes) and Stripe's wire format (integer minor units), plus the
state-machine mapping between Stripe events and ``PaymentIntent`` rows.

All money handling goes through this module — never call ``stripe.*``
directly from a router or tool.
"""
from __future__ import annotations

import base64
import json
import logging
import re
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
    AgentMessage,
    AgentMessageRole,
    AgentSession,
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
from app.errors import (
    ErrorCategory,
    UserFacingError,
    translate_filing_error,
    translate_stripe_error,
)
from app.users.models import User

logger = logging.getLogger(__name__)


class StripeServiceError(UserFacingError):
    """Domain-level Stripe failure that should surface to the caller.

    Extends :class:`app.errors.UserFacingError` so the FastAPI
    exception handler can convert it into a clean response without
    leaking the raw technical detail. Callers should pass a friendly
    ``user_message`` describing what the end user should do; the
    underlying technical context goes into ``technical_detail``.
    """

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(
            user_message=user_message
            or "We could not process this payment request. Please try again.",
            technical_detail=message,
            category=ErrorCategory.payment,
            http_status=http_status,
        )
        # Keep ``str(exc)`` the technical message for backward
        # compatibility with existing log lines and ``raise ... from exc``.
        self.args = (message,)


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
        raise StripeServiceError(
            f"No case_draft found with id {case_draft_id}.",
            user_message="This filing draft could not be found.",
            http_status=404,
        )
    if draft.user_id != user.id:
        raise StripeServiceError(
            "case_draft does not belong to the authenticated user.",
            user_message="You do not have access to this filing.",
            http_status=403,
        )
    if draft.status not in (
        CaseDraftStatus.validated,
        CaseDraftStatus.awaiting_payment,
    ):
        raise StripeServiceError(
            f"case_draft.status is '{draft.status.value}'; payment can only "
            "be prepared once the draft has been validated.",
            user_message=(
                "This filing is not ready for payment yet. "
                "Please finish reviewing the application first."
            ),
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
        translated = translate_stripe_error(exc)
        raise StripeServiceError(
            f"Stripe rejected the session: {exc}",
            user_message=translated.user_message,
            http_status=translated.http_status,
        ) from exc

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


def _explorer_tx_url(signature: str | None) -> str | None:
    if not signature:
        return None
    cluster = "devnet" if "devnet" in settings.solana_cluster_url else "mainnet-beta"
    return f"https://explorer.solana.com/tx/{signature}?cluster={cluster}"


_FILING_STATUS_RE = re.compile(r"'(\d{3})\s+[A-Z]")


def _parse_filing_status_code(raw_error: str) -> int | None:
    """Pull the HTTP status code out of an httpx-style error string.

    httpx raises ``HTTPStatusError`` as ``"Client error '400 Bad Request' for url ..."``
    — we use the captured status code to drive ``translate_filing_error``.
    Returns ``None`` when the string does not embed a status code so the
    translator falls back to its generic message.
    """
    if not raw_error:
        return None
    match = _FILING_STATUS_RE.search(raw_error)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    # EUIPO sometimes embeds the status in the body JSON, e.g.
    # ``"status":403,"instance":"/applicants"``.
    json_match = re.search(r'"status"\s*:\s*(\d{3})', raw_error)
    if json_match:
        try:
            return int(json_match.group(1))
        except ValueError:
            return None
    return None


def _resolve_stripe_receipt_url(payment_intent_id: str | None) -> str | None:
    """Return Stripe's public hosted receipt page for the charge.

    Stripe sends this URL in the e-mail receipt; it stays accessible
    indefinitely without any login, so it is the right link to embed
    in our chat confirmation (the checkout session URL itself returns
    a "session expired" page after capture).
    """
    if not payment_intent_id:
        return None
    try:
        _require_configured()
    except StripeServiceError:
        return None
    try:
        pi = stripe.PaymentIntent.retrieve(
            payment_intent_id, expand=["latest_charge"]
        )
        charge = getattr(pi, "latest_charge", None)
        if charge and not isinstance(charge, str):
            url = getattr(charge, "receipt_url", None)
            if url:
                return url
    except stripe.StripeError as exc:
        logger.warning(
            "Could not resolve Stripe receipt URL for %s: %s",
            payment_intent_id,
            exc,
        )
    return None


async def _push_chat_confirmation(
    db: AsyncSession,
    *,
    session_id: uuid.UUID | None,
    title: str,
    body_lines: list[str],
    details_json: dict[str, Any] | None = None,
) -> None:
    """Persist an assistant message into the agent chat session.

    Webhook handlers call this after a Stripe-paid payment finishes
    its compliance + attestation pipeline so the chat keeps flowing
    rather than stalling on the "Pay with card" step. The frontend
    poll picks up the new message on the next /messages refresh.

    Failures are absorbed — the payment itself is more important
    than the chat notification.
    """
    if session_id is None:
        return

    parts = [title.strip(), ""]
    parts.extend(line for line in body_lines if line)
    if details_json:
        # The chat's renderMarkdown turns a ``` fence into a collapsible
        # <details> block; the language tag (json) labels the summary.
        parts.append("")
        parts.append("```json")
        parts.append(json.dumps(details_json, indent=2, default=str))
        parts.append("```")

    content = "\n".join(parts).rstrip() + "\n"

    try:
        session_row = (
            await db.execute(
                select(AgentSession).where(AgentSession.id == session_id)
            )
        ).scalar_one_or_none()
        if session_row is None:
            return
        msg = AgentMessage(
            session_id=session_id,
            role=AgentMessageRole.assistant,
            content=content,
            input_tokens=0,
            output_tokens=0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(msg)
        await db.flush()
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to push payment confirmation message to session %s",
            session_id,
        )


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
    # Row-level lock so the webhook and the success-url reconcile path
    # cannot race: whichever side acquires the lock first runs the
    # pipeline; the other waits for that transaction to commit, then
    # observes ``auto_submit_committed_at`` and returns early. Without
    # this lock the user saw the chat confirmation message twice
    # because both paths reached ``_push_chat_confirmation``.
    locked_row = (
        await db.execute(
            select(PaymentIntent)
            .where(PaymentIntent.id == intent.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked_row is None:
        return
    await db.refresh(intent)
    if (intent.gateway_metadata or {}).get("auto_submit_committed_at"):
        return

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
        raw_error = outcome.get("error") or ""
        # Translate raw EUIPO HTTP body into a user-friendly message
        # before persisting; the raw detail still lands on the
        # FilingAttempt row (request_payload / error_message) for
        # operator debugging.
        status_code = _parse_filing_status_code(raw_error)
        friendly = translate_filing_error(
            status_code=status_code, raw_detail=raw_error
        )
        metadata["filing_error"] = friendly.user_message
        metadata["filing_error_technical"] = raw_error[:500]
        logger.warning(
            "EUIPO auto-submit FAIL draft=%s attempt=%s err=%s",
            draft.id,
            outcome.get("filing_attempt_id"),
            raw_error,
        )
        # Permanent rejection (400 validation / 404 missing / 422
        # unprocessable) → refund immediately. Transient codes (401
        # auth expired, 403 missing role, 5xx) keep the money parked
        # so the operator can fix and retry.
        if _should_auto_refund(raw_error):
            intent.gateway_metadata = metadata
            try:
                await refund_payment_intent(
                    db,
                    intent,
                    reason=(
                        f"EUIPO rejected the submission permanently "
                        f"(status={status_code}). Auto-refunded so the "
                        "customer is made whole without operator action."
                    ),
                    initiated_by="auto_euipo_permanent_failure",
                )
            except StripeServiceError as refund_exc:
                logger.exception(
                    "Auto-refund failed for intent %s: %s",
                    intent.id,
                    refund_exc,
                )
            return  # Skip downstream compliance / NFT setup — refunded
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
    # case_id is set by M5 (promote_draft_and_setup_nft); default
    # to None so the trailing chat-push code can reference it even
    # when compliance/attestation short-circuits before M5 runs.
    case_id: uuid.UUID | None = None

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

    # Chat-side notification — keep the conversation flowing after the
    # async webhook lands. Pulls the latest metadata so links are
    # accurate even if any earlier step half-failed.
    meta = intent.gateway_metadata or {}
    platform_label = meta.get("platform") or "EUIPO"
    amount_fmt = f"€{float(intent.amount):.2f}" if intent.currency.upper() == "EUR" else (
        f"{float(intent.amount):.2f} {intent.currency.upper()}"
    )
    stripe_pi_id = intent.gateway_payment_id
    # Resolve the post-payment hosted receipt URL once and cache on
    # intent metadata so subsequent webhook retries do not hit Stripe
    # again. The pre-payment checkout_url is useless after capture
    # ("session expired" landing page).
    receipt_url = meta.get("stripe_receipt_url")
    if not receipt_url and stripe_pi_id:
        receipt_url = _resolve_stripe_receipt_url(stripe_pi_id)
        if receipt_url:
            meta = dict(meta)
            meta["stripe_receipt_url"] = receipt_url
            intent.gateway_metadata = meta
    compliance_tx = meta.get("compliance_onchain_tx")
    compliance_tx_url = _explorer_tx_url(compliance_tx)
    filing_ref = meta.get("filing_external_reference")
    filing_error = meta.get("filing_error")
    body_lines = [
        f"- Provider: **Stripe** ({stripe_pi_id or '-'})",
        f"- Amount: **{amount_fmt}**",
    ]
    if receipt_url:
        body_lines.append(f"- Stripe receipt: [view receipt]({receipt_url})")
    if compliance_tx_url:
        body_lines.append(
            f"- Compliance proof on-chain (Solana): [{compliance_tx[:12]}…]({compliance_tx_url})"
        )
    if filing_ref:
        body_lines.append(f"- {platform_label} submission: **{filing_ref}**")
    elif filing_error:
        body_lines.append(
            f"- {platform_label} submission failed: {filing_error[:120]}"
        )
    else:
        body_lines.append(f"- {platform_label} submission queued.")
    # NFT info — case promotion synchronously kicks off Token-2022
    # setup; by the time we reach this push, ``nft_state``,
    # ``nft_mint`` and ``nft_setup_tx`` are populated on the case row
    # (the actual user claim happens later from the case page). Read
    # the freshest case state so the chat shows the live mint
    # address, the setup tx link, and a deep link to the claim
    # panel rather than the stale "running in background" line.
    nft_state_label: str | None = None
    nft_mint_addr: str | None = None
    nft_setup_tx: str | None = None
    case_number: str | None = None
    if case_id is not None:
        from app.cases.models import Case as _CaseRow

        _case = (
            await db.execute(select(_CaseRow).where(_CaseRow.id == case_id))
        ).scalar_one_or_none()
        if _case is not None:
            case_number = _case.case_number
            nft_state_label = (
                _case.nft_state.value
                if _case.nft_state is not None
                else None
            )
            nft_mint_addr = _case.nft_mint
            nft_setup_tx = _case.nft_setup_tx
    if case_id is not None:
        case_url = f"/dashboard/cases/{case_id}"
        case_link_label = case_number or str(case_id)[:8]
        body_lines.append(
            f"- Case promoted: [{case_link_label}]({case_url})"
        )
        if nft_mint_addr:
            setup_tx_url = _explorer_tx_url(nft_setup_tx)
            tx_suffix = (
                f" · setup tx: [{nft_setup_tx[:10]}…]({setup_tx_url})"
                if setup_tx_url
                else ""
            )
            body_lines.append(
                f"- NFT mint ready (`{nft_mint_addr[:10]}…`{tx_suffix})"
            )
            if nft_state_label == "pending_claim":
                body_lines.append(
                    f"- Claim your NFT certificate: [open case]({case_url})"
                )
        else:
            body_lines.append("- NFT setup running in background.")
    details = {
        "stripe_payment_intent_id": stripe_pi_id,
        "stripe_session_id": meta.get("stripe_session_id"),
        "compliance_artifact_id": meta.get("compliance_artifact_id"),
        "compliance_onchain_tx": compliance_tx,
        "compliance_query_hash_hex": meta.get("compliance_query_hash_hex"),
        "case_id": str(case_id) if case_id else None,
        "case_number": case_number,
        "nft_state": nft_state_label,
        "nft_mint": nft_mint_addr,
        "nft_setup_tx": nft_setup_tx,
        "filing_attempt_id": meta.get("filing_attempt_id"),
        "filing_external_reference": filing_ref,
        "filing_status": meta.get("filing_status"),
    }
    await _push_chat_confirmation(
        db,
        session_id=draft.session_id,
        title=f"✓ Payment received — {platform_label} filing pipeline running",
        body_lines=body_lines,
        details_json=details,
    )

    # Opt-in email — only fires for users who explicitly enabled it
    # and have either ``notification_email`` or login ``email`` set.
    # Fire-and-forget so a flaky email relay does not slow the webhook
    # response and trigger Stripe retries.
    from app.notifications.email_dispatcher import (
        payment_received_content,
        schedule_notification,
    )

    # Resolve case_number for the email body (chat already has it).
    case_number_label: str | None = None
    if case_id is not None:
        from app.cases.models import Case as _Case

        case_row = (
            await db.execute(select(_Case).where(_Case.id == case_id))
        ).scalar_one_or_none()
        if case_row is not None:
            case_number_label = case_row.case_number

    schedule_notification(
        db,
        user_id=draft.user_id,
        content=payment_received_content(
            amount_label=amount_fmt,
            platform=platform_label,
            case_number=case_number_label,
            stripe_receipt_url=receipt_url,
            compliance_tx_url=compliance_tx_url,
        ),
    )

    # Idempotency marker — paired with the SELECT FOR UPDATE at the
    # top of this function. Stamped only after the chat push + email
    # dispatch so any retried run that picks up the lock observes the
    # committed marker and returns without re-pushing.
    final_meta = dict(intent.gateway_metadata or {})
    final_meta["auto_submit_committed_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    intent.gateway_metadata = final_meta


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------


# Filing failure shapes we consider permanent — refunding immediately
# is safer than holding the user's money while we wait for an EUIPO
# fix that will not come (the request itself is the problem, not the
# upstream service).
_AUTO_REFUND_FILING_STATUS_CODES = {400, 404, 422}


def _should_auto_refund(raw_filing_error: str) -> bool:
    """Decide whether an EUIPO failure warrants an automatic refund.

    Returns True only when the upstream rejected the *filing request*
    itself (validation / not-found / unprocessable on ``/applications``).
    401/403/5xx keep the money parked so the operator can fix the
    integration and retry. Auth-endpoint failures (token refresh on
    ``/oidc/accessToken``) NEVER trigger a refund — those are pure
    operator-side problems; the customer's filing has not been
    rejected by EUIPO at all.
    """
    if not raw_filing_error:
        return False
    # Distinguish auth-endpoint 4xx from filing-endpoint 4xx by
    # looking at the URL embedded in the error string. An ``EuipoAuthError``
    # message contains "refresh exchange" or the access-token URL —
    # neither should trigger a refund.
    lowered = raw_filing_error.lower()
    if "accesstoken" in lowered or "refresh exchange" in lowered or (
        "operator must re-run" in lowered
    ):
        return False
    status_code = _parse_filing_status_code(raw_filing_error)
    if status_code is None:
        return False
    return status_code in _AUTO_REFUND_FILING_STATUS_CODES


async def refund_payment_intent(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    reason: str,
    initiated_by: str = "operator",
) -> PaymentIntent:
    """Issue a Stripe refund for the given ``PaymentIntent`` row.

    Real Stripe ``Refund.create`` call — money actually moves back to
    the customer's card. Idempotent: re-calling on an already-refunded
    intent returns the existing row unchanged.

    ``reason`` is recorded on ``intent.gateway_metadata.refund_reason``
    so an operator can later audit why a refund was issued without
    digging through chat history. ``initiated_by`` distinguishes
    ``"operator"`` (manual admin endpoint) from ``"auto"`` (the
    auto-submit hook's permanent-failure path).
    """
    _require_configured()

    if intent.status == PaymentIntentStatus.refunded:
        return intent
    if intent.status != PaymentIntentStatus.confirmed:
        raise StripeServiceError(
            f"Refund requested for intent {intent.id} but status is "
            f"'{intent.status.value}' — only 'confirmed' intents can be refunded.",
            user_message="This payment cannot be refunded in its current state.",
            http_status=409,
        )
    if intent.provider != PaymentProvider.stripe:
        raise StripeServiceError(
            f"Refund requested for {intent.provider.value} intent — only "
            "Stripe payments can be refunded through this endpoint.",
            user_message="Wallet payments cannot be refunded automatically.",
            http_status=400,
        )

    stripe_pi_id = intent.gateway_payment_id
    if not stripe_pi_id:
        raise StripeServiceError(
            f"Intent {intent.id} has no gateway_payment_id; cannot refund.",
            user_message="This payment is missing its Stripe id; please contact support.",
            http_status=500,
        )

    idempotency_key = f"intent:{intent.id}:refund"

    try:
        refund = stripe.Refund.create(
            payment_intent=stripe_pi_id,
            reason="requested_by_customer",
            metadata={
                "payment_intent_id": str(intent.id),
                "case_draft_id": str(intent.case_draft_id),
                "initiated_by": initiated_by,
                "reason_summary": reason[:200],
            },
            idempotency_key=idempotency_key,
        )
    except stripe.StripeError as exc:
        translated = translate_stripe_error(exc)
        raise StripeServiceError(
            f"Stripe refund creation failed: {exc}",
            user_message=translated.user_message,
            http_status=translated.http_status,
        ) from exc

    # ``charge.refunded`` webhook will also flip the intent state, but
    # we don't want to wait — update synchronously so the response
    # returns the right shape and the chat push fires immediately.
    intent.status = PaymentIntentStatus.refunded
    metadata = dict(intent.gateway_metadata or {})
    metadata["stripe_refund_id"] = refund.id
    metadata["refund_reason"] = reason
    metadata["refund_initiated_by"] = initiated_by
    metadata["refunded_amount"] = getattr(refund, "amount", None)
    intent.gateway_metadata = metadata
    await db.flush()

    # Best-effort chat notification — the user should know without
    # having to check their bank statement.
    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == intent.case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is not None:
        amount_fmt = (
            f"€{float(intent.amount):.2f}"
            if intent.currency.upper() == "EUR"
            else f"{float(intent.amount):.2f} {intent.currency.upper()}"
        )
        body = [
            f"- Provider: **Stripe** ({stripe_pi_id})",
            f"- Refunded amount: **{amount_fmt}**",
            f"- Stripe refund id: `{refund.id}`",
            f"- Reason: {reason}",
            "",
            "The card-issuing bank usually shows the refund within 5-10 "
            "business days. No further action required from you.",
        ]
        await _push_chat_confirmation(
            db,
            session_id=draft.session_id,
            title=f"↩ Payment refunded — {amount_fmt} returned to your card",
            body_lines=body,
            details_json={
                "stripe_refund_id": refund.id,
                "stripe_payment_intent_id": stripe_pi_id,
                "refund_reason": reason,
                "initiated_by": initiated_by,
            },
        )
        # Opt-in email — same gating as the payment-received path.
        from app.notifications.email_dispatcher import (
            refund_issued_content,
            schedule_notification,
        )

        schedule_notification(
            db,
            user_id=draft.user_id,
            content=refund_issued_content(
                amount_label=amount_fmt,
                reason=reason,
                stripe_refund_id=refund.id,
            ),
        )

    logger.info(
        "Stripe refund issued intent=%s refund=%s initiated_by=%s",
        intent.id,
        refund.id,
        initiated_by,
    )
    return intent


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
    # Webhook payloads arrive as stripe.StripeObject which supports
    # subscript access but NOT the dict ``.get()`` API. Normalize so
    # both webhook and reconcile paths can use ``.get()`` uniformly.
    if hasattr(session, "to_dict_recursive"):
        session = session.to_dict_recursive()
    elif hasattr(session, "to_dict"):
        session = session.to_dict()

    # UKIPO sessions don't have a PaymentIntent row in our table —
    # they're tracked directly on UKIPOSubmission. Route them to the
    # dedicated handler.
    metadata = session.get("metadata") or {}
    if metadata.get("lane") == "ukipo":
        return await _handle_ukipo_session_completed(db, session)

    # Renewal lane — a renewal Checkout session carries
    # ``intent_kind="renewal"`` in metadata. We skip the
    # compliance/attestation/NFT/submit pipeline (the case already
    # exists with all three) and only advance the renewal cycle.
    if metadata.get("intent_kind") == "renewal":
        return await _handle_renewal_session_completed(db, session)

    intent = await _lookup_intent_by_session(db, session)
    if intent is None:
        logger.warning(
            "checkout.session.completed received for unknown session %s",
            session.get("id"),
        )
        return {"handled": False, "reason": "intent_not_found"}

    # Acquire row-level lock + refresh BEFORE any in-memory metadata
    # mutation. The webhook and the success-url reconciler race the
    # same intent; whichever side acquires the lock first runs the
    # pipeline to completion. The other side waits for the commit,
    # then refresh() reflects the post-commit metadata so the
    # ``auto_submit_committed_at`` short-circuit fires correctly.
    # Without this, the second-arriving handler reads STALE
    # in-memory metadata, writes a new dict back via the implicit
    # UPDATE, and silently overwrites the first handler's marker.
    await db.execute(
        select(PaymentIntent)
        .where(PaymentIntent.id == intent.id)
        .with_for_update()
    )
    await db.refresh(intent)
    if (intent.gateway_metadata or {}).get("auto_submit_committed_at"):
        return {"handled": True, "reason": "already_processed"}

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


async def create_ukipo_checkout_session(
    db: AsyncSession,
    *,
    user: User,
    submission_id: uuid.UUID,
) -> tuple[str, str, int]:
    """Open a Stripe Checkout session for a UKIPO ``awaiting_payment`` submission.

    Returns ``(checkout_url, stripe_session_id, unit_amount)``. The
    submission row is updated with the Stripe correlation ids so the
    webhook + reconcile path can find it later.

    Ownership is enforced through the linked Case row — the
    authenticated user must be the case owner (or admin) before we
    let them pay.
    """
    _require_configured()

    # Local imports keep the payments module decoupled from UKIPO
    # internals (the M1 EUIPO path does not touch any of these
    # symbols at all).
    from app.cases.models import Case
    from app.services.ukipo.models import (
        UKIPOSubmission,
        UKIPOSubmissionStatus,
    )

    submission = (
        await db.execute(
            select(UKIPOSubmission).where(UKIPOSubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if submission is None:
        raise StripeServiceError(
            f"UKIPO submission {submission_id} not found.",
            user_message="This UK IPO filing could not be found.",
            http_status=404,
        )

    case = (
        await db.execute(select(Case).where(Case.id == submission.case_id))
    ).scalar_one_or_none()
    if case is None:
        raise StripeServiceError(
            f"UKIPO submission {submission_id} has no backing case.",
            user_message="This UK IPO filing is missing its underlying case record.",
            http_status=404,
        )
    if case.client_id != user.id and user.role.value != "admin":
        raise StripeServiceError(
            "UKIPO submission does not belong to the authenticated user.",
            user_message="You do not have access to this filing.",
            http_status=403,
        )

    if submission.status != UKIPOSubmissionStatus.awaiting_payment:
        raise StripeServiceError(
            f"UKIPO submission status is '{submission.status.value}'; "
            "Stripe payment can only be opened at awaiting_payment.",
            user_message=(
                "This UK IPO filing is not waiting for payment right now "
                "(the robot is still preparing the application or it is "
                "already paid)."
            ),
        )

    # UK IPO published filing fee per the robot's payment-requirements
    # endpoint: £265 GBP for a single-class trade mark application.
    # Stripe-billed amounts use minor units (pence).
    currency = "gbp"
    unit_amount = 26500

    idempotency_key = f"ukipo_submission:{submission.id}:stripe"

    # If a previous checkout for this submission is still open we
    # reuse it instead of stacking sessions.
    if (
        submission.stripe_checkout_session_id
        and submission.stripe_confirmed_at is None
    ):
        try:
            existing_session = stripe.checkout.Session.retrieve(
                submission.stripe_checkout_session_id
            )
            if existing_session.status == "open" and existing_session.url:
                return (
                    existing_session.url,
                    existing_session.id,
                    unit_amount,
                )
        except stripe.StripeError as exc:  # noqa: BLE001
            logger.warning(
                "Failed to retrieve existing UKIPO session %s: %s",
                submission.stripe_checkout_session_id,
                exc,
            )

    product_name = (
        f"UK IPO trademark filing — “{case.title}”"
        if case.title
        else "UK IPO trademark filing"
    )
    description = (
        f"UK IPO platform fee (£{unit_amount/100:.2f} GBP). "
        f"Robot submission id {submission.id}."
    )

    session_kwargs: dict[str, Any] = {
        "mode": "payment",
        "payment_method_types": ["card"],
        "line_items": [
            {
                "price_data": {
                    "currency": currency,
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
        "client_reference_id": str(submission.id),
        "metadata": {
            "lane": "ukipo",
            "submission_id": str(submission.id),
            "case_id": str(case.id),
            "user_id": str(user.id),
        },
        "payment_intent_data": {
            "metadata": {
                "lane": "ukipo",
                "submission_id": str(submission.id),
                "case_id": str(case.id),
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
        logger.exception("Stripe UKIPO checkout.Session.create failed")
        translated = translate_stripe_error(exc)
        raise StripeServiceError(
            f"Stripe rejected the session: {exc}",
            user_message=translated.user_message,
            http_status=translated.http_status,
        ) from exc

    if not session.url:
        raise StripeServiceError(
            "Stripe returned a UKIPO session without a redirect URL.",
            user_message=(
                "Could not start the payment session. Please refresh and try again."
            ),
            http_status=502,
        )

    submission.stripe_checkout_session_id = session.id
    submission.stripe_payment_intent_id = session.payment_intent
    submission.stripe_amount_minor = unit_amount
    submission.stripe_currency = currency.upper()
    await db.commit()

    return session.url, session.id, unit_amount


async def _handle_renewal_session_completed(
    db: AsyncSession, session: dict[str, Any]
) -> dict[str, Any]:
    """Finalize a successful renewal Checkout.

    Renewals reuse the existing PaymentIntent table (so refunds,
    admin panel, etc. all work the same way) but DO NOT trigger
    submit_eutm / compliance / NFT setup — the case already has all
    three. The handler simply:
      1. Confirms the intent (status, gateway_payment_id, metadata).
      2. Calls mark_case_renewed → advances renewal_due_at by another
         10y term and stamps last_renewed_at.
      3. Pushes the same chat confirmation channel + opt-in email
         the user is used to for payments.
    """
    if hasattr(session, "to_dict_recursive"):
        session = session.to_dict_recursive()
    elif hasattr(session, "to_dict"):
        session = session.to_dict()

    intent = await _lookup_intent_by_session(db, session)
    if intent is None:
        logger.warning(
            "renewal checkout.session.completed for unknown intent %s",
            session.get("id"),
        )
        return {"handled": False, "reason": "intent_not_found"}

    await db.execute(
        select(PaymentIntent)
        .where(PaymentIntent.id == intent.id)
        .with_for_update()
    )
    await db.refresh(intent)
    if (intent.gateway_metadata or {}).get("renewal_committed_at"):
        return {"handled": True, "reason": "already_processed"}

    if intent.status in _TERMINAL_STATUSES:
        return {"handled": False, "reason": "already_terminal"}

    payment_status = session.get("payment_status")
    if payment_status != "paid":
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
    md = dict(intent.gateway_metadata or {})
    md["stripe_session_status"] = session.get("status")
    md["payment_status"] = payment_status
    intent.gateway_metadata = md

    case_id_str = (
        (session.get("metadata") or {}).get("case_id")
        or md.get("renewal_case_id")
    )
    if not case_id_str:
        logger.warning(
            "renewal intent %s missing case_id metadata; cannot advance",
            intent.id,
        )
        return {"handled": False, "reason": "case_id_missing"}
    try:
        case_id = uuid.UUID(case_id_str)
    except (TypeError, ValueError):
        return {"handled": False, "reason": "case_id_invalid"}

    case = (
        await db.execute(select(Case).where(Case.id == case_id))
    ).scalar_one_or_none()
    if case is None:
        return {"handled": False, "reason": "case_not_found"}

    from app.renewals.service import mark_case_renewed
    await mark_case_renewed(db, case)

    md = dict(intent.gateway_metadata or {})
    md["renewal_committed_at"] = datetime.now(timezone.utc).isoformat()
    md["renewal_new_due_at"] = (
        case.renewal_due_at.isoformat() if case.renewal_due_at else None
    )
    intent.gateway_metadata = md

    # Chat-side confirmation + opt-in email reuse the existing
    # infrastructure so the user gets a consistent post-payment
    # experience whether the payment was for the initial filing or a
    # renewal.
    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == intent.case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is not None and draft.session_id is not None:
        await _push_chat_confirmation(
            db,
            session_id=draft.session_id,
            title=f"✓ Renewal received — {case.case_number}",
            body_lines=[
                f"- Trademark **{case.case_number}** "
                f"({case.title or case.case_number}) renewed.",
                f"- New protection runs until **{case.renewal_due_at.date().isoformat() if case.renewal_due_at else '-'}**.",
                f"- Stripe payment intent: `{intent.gateway_payment_id or '-'}`",
            ],
            details_json={
                "case_id": str(case.id),
                "intent_id": str(intent.id),
                "new_renewal_due_at": (
                    case.renewal_due_at.isoformat()
                    if case.renewal_due_at
                    else None
                ),
            },
        )

    if case.client_id is not None:
        from app.notifications.email_dispatcher import (
            NotificationContent,
            schedule_notification,
        )
        schedule_notification(
            db,
            user_id=case.client_id,
            content=NotificationContent(
                subject=f"Renewal confirmed — {case.case_number}",
                message=(
                    f"Your trademark {case.case_number} has been "
                    f"renewed. New due date: "
                    f"{case.renewal_due_at.date().isoformat() if case.renewal_due_at else '-'}."
                ),
            ),
        )

    await db.commit()
    return {
        "handled": True,
        "intent_id": str(intent.id),
        "case_id": str(case.id),
        "new_renewal_due_at": (
            case.renewal_due_at.isoformat() if case.renewal_due_at else None
        ),
    }


async def _handle_ukipo_session_completed(
    db: AsyncSession, session: dict[str, Any]
) -> dict[str, Any]:
    """Advance a UKIPO submission past awaiting_payment after Stripe confirms.

    Does in one pass what the x402 confirm-payment endpoint does for
    wallet payers: re-derives the canonical query_hash from the
    UKIPOSubmission row, generates a Groth16 compliance proof
    server-side, submits the verify_compliance_proof tx via the
    operator, and flips ``submission.status`` to ``filed``. Idempotent
    against repeated webhook delivery.
    """
    from app.compliance.service import (
        derive_query_hash,
        derive_secret,
        _run_prover,
    )
    from app.services.ukipo.models import (
        UKIPOSubmission,
        UKIPOSubmissionStatus,
    )

    submission_id_raw = (session.get("metadata") or {}).get("submission_id")
    try:
        submission_id = uuid.UUID(submission_id_raw)
    except (TypeError, ValueError):
        logger.warning(
            "UKIPO Stripe session %s missing/invalid submission_id metadata",
            session.get("id"),
        )
        return {"handled": False, "reason": "missing_submission_id"}

    submission = (
        await db.execute(
            select(UKIPOSubmission).where(UKIPOSubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if submission is None:
        logger.warning(
            "UKIPO Stripe session %s references unknown submission %s",
            session.get("id"),
            submission_id,
        )
        return {"handled": False, "reason": "submission_not_found"}

    if submission.status == UKIPOSubmissionStatus.filed:
        return {"handled": False, "reason": "already_filed"}

    if session.get("payment_status") != "paid":
        return {"handled": True, "status": "pending_async_payment"}

    stripe_pi = session.get("payment_intent")
    if stripe_pi:
        submission.stripe_payment_intent_id = stripe_pi
    submission.stripe_confirmed_at = datetime.now(timezone.utc)

    # Build the canonical filing-context query_hash exactly the same
    # way the existing x402 confirm-payment path does, so the proof
    # commits to the same logical filing.
    case_draft_uuid = submission.id  # we use submission_id as the binding key for UKIPO
    mark_text = submission.mark_text if hasattr(submission, "mark_text") else None
    # UKIPOSubmission stores nice classes off the linked Case row.
    nice_classes = _ukipo_nice_classes(submission)
    query_hash = derive_query_hash(
        case_draft_id=submission.id,
        mark_text=submission.mark_text if hasattr(submission, "mark_text") else None,
        nice_classes=nice_classes,
        platform="UKIPO",
        stripe_payment_intent_id=stripe_pi or "",
    )
    secret = derive_secret(
        stripe_payment_intent_id=stripe_pi or "",
        query_hash=query_hash,
    )

    try:
        prover_output = await _run_prover(secret=secret, query_hash=query_hash)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "UKIPO compliance prover failed for submission %s",
            submission.id,
        )
        await db.commit()
        return {"handled": True, "status": "prover_failed", "error": str(exc)}

    submission.solana_query_hash_hex = query_hash.hex()
    # solana_commitment_hex is VARCHAR(64) — store 64-char BE hex,
    # not the (up to 77-digit) decimal representation the prover emits.
    commitment_int = int(prover_output["commitment_dec"])
    submission.solana_commitment_hex = commitment_int.to_bytes(32, "big").hex()

    proof_a = base64.b64decode(prover_output["onchain"]["proof_a_b64"])
    proof_b = base64.b64decode(prover_output["onchain"]["proof_b_b64"])
    proof_c = base64.b64decode(prover_output["onchain"]["proof_c_b64"])
    public_inputs = [
        base64.b64decode(b)
        for b in prover_output["onchain"]["public_inputs_b64"]
    ]

    if settings.solana_zk_verifier_enabled:
        try:
            from app.solana.client import (
                _load_operator,
                submit_compliance_proof_tx,
            )
            from solders.pubkey import Pubkey

            # Anchor the ComplianceRecord PDA under the operator
            # pubkey when no wallet is bound. M5's wallet-required
            # design tightens this for production.
            operator = _load_operator()
            user_pubkey = (
                Pubkey.from_string(submission.solana_payer_wallet)
                if submission.solana_payer_wallet
                else operator.pubkey()
            )
            signature, pda = await submit_compliance_proof_tx(
                user_pubkey,
                proof_a,
                proof_b,
                proof_c,
                public_inputs,
                query_hash,
            )
            submission.solana_compliance_tx = signature
            submission.solana_compliance_pda = str(pda)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "UKIPO on-chain attestation failed for submission %s",
                submission.id,
            )
            await db.commit()
            return {"handled": True, "status": "attestation_failed", "error": str(exc)}

    submission.status = UKIPOSubmissionStatus.filed
    submission.finished_at = datetime.now(timezone.utc)
    await db.commit()

    # Chat-side notification: find the agent_session via the linked
    # case_draft (case_draft.session_id maps to the chat that opened
    # this UKIPO flow).
    from app.agent.models import CaseDraft as _CaseDraft

    session_id_for_chat: uuid.UUID | None = None
    if submission.case_id:
        draft_row = (
            await db.execute(
                select(_CaseDraft).where(
                    _CaseDraft.promoted_case_id == submission.case_id
                )
            )
        ).scalar_one_or_none()
        if draft_row is not None:
            session_id_for_chat = draft_row.session_id

    compliance_tx_url = _explorer_tx_url(submission.solana_compliance_tx)
    amount_minor = submission.stripe_amount_minor or 26500
    amount_fmt = f"£{amount_minor/100:.2f}"
    receipt_url = _resolve_stripe_receipt_url(
        submission.stripe_payment_intent_id
    )
    body_lines = [
        f"- Provider: **Stripe** ({submission.stripe_payment_intent_id or '-'})",
        f"- Amount: **{amount_fmt}**",
    ]
    if receipt_url:
        body_lines.append(f"- Stripe receipt: [view receipt]({receipt_url})")
    if compliance_tx_url:
        body_lines.append(
            f"- Compliance proof on-chain (Solana): "
            f"[{submission.solana_compliance_tx[:12]}…]({compliance_tx_url})"
        )
    body_lines.append(f"- UK IPO submission: **filed** (status=filed)")
    body_lines.append("- NFT mint already set up; claim available below.")
    details = {
        "submission_id": str(submission.id),
        "case_id": str(submission.case_id) if submission.case_id else None,
        "stripe_payment_intent_id": submission.stripe_payment_intent_id,
        "stripe_amount_minor": amount_minor,
        "stripe_currency": submission.stripe_currency,
        "solana_query_hash_hex": submission.solana_query_hash_hex,
        "solana_commitment_hex": submission.solana_commitment_hex,
        "solana_compliance_tx": submission.solana_compliance_tx,
        "solana_compliance_pda": submission.solana_compliance_pda,
    }
    await _push_chat_confirmation(
        db,
        session_id=session_id_for_chat,
        title="✓ Payment received — UK IPO filing complete",
        body_lines=body_lines,
        details_json=details,
    )

    # Opt-in email — the chat covers in-app; this covers the user who
    # closed the tab after paying. ``draft_row`` (resolved earlier
    # via promoted_case_id) carries the user_id we need.
    if draft_row is not None:
        from app.cases.models import Case as _Case
        from app.notifications.email_dispatcher import (
            filing_submitted_content,
            payment_received_content,
            schedule_notification,
        )

        case_row = (
            await db.execute(select(_Case).where(_Case.id == submission.case_id))
        ).scalar_one_or_none()
        case_number_label = case_row.case_number if case_row else None
        schedule_notification(
            db,
            user_id=draft_row.user_id,
            content=payment_received_content(
                amount_label=amount_fmt,
                platform="UK IPO",
                case_number=case_number_label,
                stripe_receipt_url=receipt_url,
                compliance_tx_url=compliance_tx_url,
            ),
        )
        # Separate "filing submitted" notification since UKIPO
        # actually lands as filed in the same hook (EUIPO is async;
        # UKIPO robot already did the work upstream).
        schedule_notification(
            db,
            user_id=draft_row.user_id,
            content=filing_submitted_content(
                platform="UK IPO",
                external_reference=submission.ipo_reference or "pending",
                case_number=case_number_label,
            ),
        )

    await db.commit()

    return {
        "handled": True,
        "status": "filed",
        "submission_id": str(submission.id),
        "compliance_tx": submission.solana_compliance_tx,
    }


def _ukipo_nice_classes(submission: Any) -> list[int]:
    """Best-effort extraction of integer nice classes from a UKIPO row.

    The submission stores classes either as JSON on a related field or
    on the linked Case row; either way we collapse to a list of ints
    so ``derive_query_hash`` produces a stable canonical hash.
    """
    raw = getattr(submission, "nice_classes", None) or []
    out: list[int] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict):
                num = item.get("class_number") or item.get("number")
            else:
                num = item
            try:
                out.append(int(num))
            except (TypeError, ValueError):
                continue
    return sorted(set(out))


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
        translated = translate_stripe_error(exc)
        raise StripeServiceError(
            f"Stripe rejected session lookup: {exc}",
            user_message=translated.user_message,
            http_status=translated.http_status,
        ) from exc

    intent = await _lookup_intent_by_session(db, session.to_dict())
    if intent is None:
        raise StripeServiceError(
            f"No payment_intent found for session {session_id}.",
            user_message="This payment session was not found.",
            http_status=404,
        )

    draft = (
        await db.execute(
            select(CaseDraft).where(CaseDraft.id == intent.case_draft_id)
        )
    ).scalar_one_or_none()
    if draft is None or draft.user_id != user.id:
        raise StripeServiceError(
            "Session does not belong to the authenticated user.",
            user_message="You do not have access to this payment.",
            http_status=403,
        )

    # Row-level lock so the webhook + success-url paths converge cleanly
    # on the same PaymentIntent. See _handle_session_completed for the
    # full rationale — without this the second-arriving handler reads
    # stale in-memory metadata and overwrites the first handler's
    # auto_submit_committed_at marker, double-firing the chat push.
    await db.execute(
        select(PaymentIntent)
        .where(PaymentIntent.id == intent.id)
        .with_for_update()
    )
    await db.refresh(intent)
    if (intent.gateway_metadata or {}).get("auto_submit_committed_at"):
        return intent

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

        # Renewal lane — the intent metadata tells us this Checkout
        # was for a 10-year renewal, NOT the original filing. Skip
        # the compliance/attestation/NFT/submit pipeline (the case
        # already has all four) and only advance the renewal cycle.
        # We also short-circuit the draft.status promotion: the
        # underlying draft was already in CaseDraftStatus.paid from
        # the original filing and we do not want to revert it.
        if metadata.get("intent_kind") == "renewal":
            case_id_str = metadata.get("renewal_case_id")
            if case_id_str:
                try:
                    case_id = uuid.UUID(case_id_str)
                except (TypeError, ValueError):
                    case_id = None
            else:
                case_id = None
            if case_id is not None:
                from app.cases.models import Case as _RenewalCase
                case = (
                    await db.execute(
                        select(_RenewalCase).where(_RenewalCase.id == case_id)
                    )
                ).scalar_one_or_none()
                if case is not None:
                    from app.renewals.service import mark_case_renewed
                    await mark_case_renewed(db, case)
                    md = dict(intent.gateway_metadata or {})
                    md["renewal_committed_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    md["renewal_new_due_at"] = (
                        case.renewal_due_at.isoformat()
                        if case.renewal_due_at
                        else None
                    )
                    intent.gateway_metadata = md
                    if draft.session_id is not None:
                        await _push_chat_confirmation(
                            db,
                            session_id=draft.session_id,
                            title=(
                                f"✓ Renewal received — {case.case_number}"
                            ),
                            body_lines=[
                                f"- Trademark **{case.case_number}** renewed.",
                                f"- New protection runs until **{case.renewal_due_at.date().isoformat() if case.renewal_due_at else '-'}**.",
                                f"- Stripe payment intent: `{intent.gateway_payment_id or '-'}`",
                            ],
                            details_json={
                                "case_id": str(case.id),
                                "intent_id": str(intent.id),
                                "new_renewal_due_at": (
                                    case.renewal_due_at.isoformat()
                                    if case.renewal_due_at
                                    else None
                                ),
                            },
                        )
        else:
            if draft.status == CaseDraftStatus.awaiting_payment:
                draft.status = CaseDraftStatus.paid
            # Auto-submit also runs from the success_url path so a
            # missing webhook does not block the filing from going
            # out. Idempotent against the webhook firing in parallel.
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

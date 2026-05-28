"""prepare_payment tool — open a payment intent for a finalized draft.

Once the user confirms they want to file, the agent calls this tool to
create a payment_intent row and flip the case_draft status to
'awaiting_payment'. The agent should then tell the user that payment
is waiting and stop. Real on-chain settlement (x402 / Solana Pay) is
performed by the frontend in a later phase; for Phase 0 the payment
intent stays in 'created' until the wallet confirms it through a
separate endpoint.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.models import (
    CaseDraft,
    CaseDraftStatus,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentProvider,
    PaymentType,
)
from app.agent.tools.base import Tool, ToolError, register
from app.agent.tools.quote_fees import _quote_euipo_trademark
from app.database import async_session

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "case_draft_id": {
            "type": "string",
            "description": "UUID of the validated case_draft to pay for.",
        },
        "platform": {
            "type": "string",
            "enum": ["EUIPO", "WIPO", "USPTO", "UKIPO"],
            "description": "IP office to pay the application fee to.",
        },
    },
    "additionalProperties": False,
    "required": ["case_draft_id", "platform"],
}


def _parse_uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise ToolError(f"{field} is not a valid UUID: {value}")


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    raw_draft_id = args.get("case_draft_id")
    # Llama-3.3 occasionally drops the required arg even though the
    # schema marks it required. Fall back to the session-scoped
    # ``CaseDraft`` (the orchestrator injects ``_session_id`` as a
    # reserved underscore-prefixed key for exactly this case);
    # case_draft has a UNIQUE constraint on session_id so this is
    # always unambiguous.
    async with async_session() as db:
        draft: CaseDraft | None = None
        if raw_draft_id:
            draft_id = _parse_uuid(raw_draft_id, "case_draft_id")
            draft = (
                await db.execute(
                    select(CaseDraft).where(CaseDraft.id == draft_id)
                )
            ).scalar_one_or_none()
        else:
            session_id_str = args.get("_session_id")
            if session_id_str:
                try:
                    session_uuid = uuid.UUID(session_id_str)
                except (TypeError, ValueError):
                    session_uuid = None
                if session_uuid is not None:
                    draft = (
                        await db.execute(
                            select(CaseDraft).where(
                                CaseDraft.session_id == session_uuid
                            )
                        )
                    ).scalar_one_or_none()
        if draft is None:
            raise ToolError(
                "case_draft_id is required and the current session has no "
                "case_draft to fall back to. Call create_case_draft first."
            )

        # Agent occasionally omits the platform arg even though the
        # schema marks it required. Fall back to the draft's selected
        # platforms (the user already picked them in create_case_draft)
        # so a one-off forgotten arg does not break the payment step.
        platform = args.get("platform")
        if not platform:
            selected = draft.selected_platforms or []
            platform = selected[0] if selected else None
        if not platform:
            raise ToolError(
                "platform is required and the case_draft has no "
                "selected_platforms; ask the user which office to file with."
            )

        if platform != "EUIPO":
            raise ToolError(
                f"Payment for {platform} is not yet wired in this milestone. "
                "Only EUIPO can be paid for right now."
            )

        if draft.status not in (
            CaseDraftStatus.validated,
            CaseDraftStatus.awaiting_payment,
        ):
            raise ToolError(
                f"case_draft.status is '{draft.status.value}'; payment can "
                "only be prepared once the draft has been validated."
            )

        nice_classes = [int(c) for c in (draft.nice_classes or [])]
        quote = _quote_euipo_trademark(nice_classes)
        amount = quote["total"]
        currency = quote["currency"]

        idempotency_key = f"draft:{draft.id}:platform_fee:EUIPO"

        existing = await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.idempotency_key == idempotency_key
            )
        )
        intent = existing.scalar_one_or_none()
        if intent is None:
            intent = PaymentIntent(
                case_draft_id=draft.id,
                payment_type=PaymentType.platform_fee,
                provider=PaymentProvider.x402,
                amount=amount,
                currency=currency,
                status=PaymentIntentStatus.created,
                idempotency_key=idempotency_key,
                gateway_metadata={
                    "platform": platform,
                    "fee_breakdown": quote["breakdown"],
                    "fee_source": quote["source"],
                    "fee_last_verified": quote["schedule_last_verified"],
                    "settlement_chain": "solana",
                    "settlement_asset": "USDC",
                    "note": (
                        "Payment is recorded as EUR; the frontend will "
                        "convert to a USDC quote at the user's wallet "
                        "approval moment via x402."
                    ),
                },
            )
            db.add(intent)
        # Else: idempotency hit, return the existing intent without changes.

        draft.status = CaseDraftStatus.awaiting_payment
        await db.commit()
        await db.refresh(intent)

        return {
            "payment_intent_id": str(intent.id),
            "case_draft_id": str(draft.id),
            "draft_status": draft.status.value,
            "intent_status": intent.status.value,
            "provider": intent.provider.value,
            "amount": float(intent.amount),
            "currency": intent.currency,
            "platform": platform,
            "user_action_required": (
                "The user must approve the payment from their wallet. The "
                "frontend will surface the x402 challenge; the agent should "
                "tell the user to complete the payment and wait."
            ),
        }


prepare_payment_tool = register(
    Tool(
        name="prepare_payment",
        description=(
            "Open a payment intent for a validated case_draft. Records a "
            "payment_intent row, flips the draft to 'awaiting_payment', "
            "and returns details the frontend uses to surface the x402 "
            "wallet challenge. Call this AFTER create_case_draft and "
            "BEFORE submit_filing. Tell the user payment is waiting once "
            "this returns; do not call submit_filing until the user has "
            "actually paid."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

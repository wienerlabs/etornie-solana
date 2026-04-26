"""BRAID-internal endpoints.

Thin reasoning-side endpoints consumed by the OpenServ BRAID agent in
``services/braid``. These wrap canonical Etornie logic (e.g. on-chain
payment verification) so the agent does not duplicate domain code.

Auth: every endpoint requires an ``X-Braid-Auth`` header that matches
``settings.braid_internal_token``. If the token is unset, the entire
router refuses requests (fail-closed). The token is shared between this
service and ``services/braid/.env``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from solders.pubkey import Pubkey

from app.config import settings
from app.solana.client import SolanaClientError, verify_payment_tx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/braid", tags=["braid"])


def _check_auth(x_braid_auth: str | None) -> None:
    if not settings.braid_internal_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "braid endpoints disabled (BRAID_INTERNAL_TOKEN unset)",
        )
    if x_braid_auth != settings.braid_internal_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing X-Braid-Auth header",
        )


class VerifyX402Request(BaseModel):
    signature: str = Field(
        ..., description="Solana transaction signature of the payment to verify"
    )
    expected_memo: str = Field(
        ...,
        description=(
            "Memo string the payment must carry; typically "
            "base58(sha256(query_hash || commitment))"
        ),
    )
    min_lamports: int | None = Field(
        default=None,
        description="Override min lamports; defaults to platform setting",
    )
    recipient_vault: str | None = Field(
        default=None,
        description="Override recipient vault pubkey; defaults to platform setting",
    )


class VerifyX402Response(BaseModel):
    verified: bool
    signature: str
    recipient_vault: str
    min_lamports_required: int
    expected_memo: str
    error: str | None = None


@router.post(
    "/verify-x402-payment",
    response_model=VerifyX402Response,
    summary="Verify an x402 SOL micropayment for the EtornieGPT flow",
)
async def verify_x402_payment(
    body: VerifyX402Request,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> VerifyX402Response:
    """Verify a Solana payment tx against the EtornieGPT vault.

    Always returns ``HTTP 200`` so the BRAID agent can reason over the
    structured outcome (success or auditable failure). Auth/config errors
    use proper HTTP status codes.
    """
    _check_auth(x_braid_auth)

    vault_str = body.recipient_vault or settings.etorniegpt_payment_vault
    if not vault_str:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "etorniegpt payment vault not configured",
        )

    min_lamports = body.min_lamports or settings.etorniegpt_payment_lamports

    try:
        recipient = Pubkey.from_string(vault_str)
    except Exception as exc:  # noqa: BLE001 - normalize all parse errors
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid recipient_vault pubkey: {exc}",
        ) from exc

    try:
        await verify_payment_tx(
            signature=body.signature,
            expected_recipient=recipient,
            min_lamports=min_lamports,
            expected_memo=body.expected_memo,
        )
    except SolanaClientError as exc:
        logger.info(
            "braid verify_x402 failed sig=%s reason=%s", body.signature, exc
        )
        return VerifyX402Response(
            verified=False,
            signature=body.signature,
            recipient_vault=vault_str,
            min_lamports_required=min_lamports,
            expected_memo=body.expected_memo,
            error=str(exc),
        )

    return VerifyX402Response(
        verified=True,
        signature=body.signature,
        recipient_vault=vault_str,
        min_lamports_required=min_lamports,
        expected_memo=body.expected_memo,
    )

"""HTTP endpoints for Solana wallet sign-in."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import (
    WalletNonceRequest,
    WalletNonceResponse,
    WalletVerifyRequest,
    WalletVerifyResponse,
    UserResponse,
)
from app.auth.utils import create_access_token, create_refresh_token
from app.auth.wallet_service import (
    AdminRoleForbidden,
    HandleGenerationFailed,
    InvalidSignature,
    InvalidWalletAddress,
    MessageMismatch,
    NonceNotFound,
    WalletAuthError,
    authenticate_or_create,
    decode_pubkey,
    generate_nonce,
    pick_jwt_subject,
    verify_signature,
)
from app.cases.guest_linking import link_guest_cases
from app.database import get_db
from app.users.models import UserRole


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/wallet", tags=["auth", "wallet"])


@router.post("/nonce", response_model=WalletNonceResponse)
async def request_wallet_nonce(payload: WalletNonceRequest) -> WalletNonceResponse:
    """Issue a single-use nonce and the message the wallet must sign."""
    try:
        decode_pubkey(payload.wallet_address)
    except InvalidWalletAddress as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid wallet address: {exc}",
        ) from exc

    nonce, message, expires_at = generate_nonce(payload.wallet_address)
    return WalletNonceResponse(
        wallet_address=payload.wallet_address,
        nonce=nonce,
        message=message,
        expires_at=expires_at,
    )


@router.post("/verify", response_model=WalletVerifyResponse)
async def verify_wallet_signature(
    payload: WalletVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> WalletVerifyResponse:
    """Verify the signed message and issue JWT tokens.

    If the wallet has no associated user, one is created with role=client,
    auth_method=wallet, and a deterministic public_handle.
    """
    try:
        verify_signature(
            payload.wallet_address, payload.message, payload.signature
        )
    except NonceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nonce missing or expired. Request a fresh nonce and retry.",
        ) from exc
    except MessageMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Submitted message does not match the issued challenge.",
        ) from exc
    except InvalidSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except InvalidWalletAddress as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid wallet address: {exc}",
        ) from exc

    role_hint: UserRole | None = (
        UserRole(payload.role) if payload.role is not None else None
    )

    try:
        user, created = await authenticate_or_create(
            db,
            payload.wallet_address,
            full_name_hint=payload.full_name,
            role_hint=role_hint,
        )
    except AdminRoleForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except HandleGenerationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not allocate a unique public handle.",
        ) from exc
    except WalletAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    if created:
        try:
            linked = await link_guest_cases(db, user)
            if linked > 0:
                logger.info(
                    "linked %d guest cases to wallet user %s",
                    linked,
                    user.public_handle,
                )
        except Exception as exc:  # noqa: BLE001 - best-effort linking
            logger.warning("wallet guest case linking failed: %s", exc)

    subject = pick_jwt_subject(user)
    return WalletVerifyResponse(
        access_token=create_access_token(subject, user.role.value),
        refresh_token=create_refresh_token(subject),
        user=UserResponse.model_validate(user),
    )

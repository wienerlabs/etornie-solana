"""HTTP endpoints for EVM wallet identity (unified identity, #74).

* POST /auth/evm/nonce  — issue a nonce + message to sign (public).
* POST /auth/evm/link   — bind the EVM address to the authenticated account.
* DELETE /auth/evm/link — unlink.
* POST /auth/evm/login  — sign in with the EVM wallet; resolves to the
  already-linked etornie account (never creates a second handle).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth import evm_service
from app.auth.schemas import (
    EvmLinkRequest,
    EvmLinkStatus,
    EvmNonceRequest,
    EvmNonceResponse,
    TokenResponse,
)
from app.auth.utils import create_access_token, create_refresh_token
from app.database import get_db
from app.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/evm", tags=["auth", "evm"])


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/nonce", response_model=EvmNonceResponse)
async def evm_nonce(payload: EvmNonceRequest) -> EvmNonceResponse:
    """Issue a single-use nonce + message for the EVM wallet to sign."""
    try:
        nonce, message, expires_at = evm_service.generate_nonce(payload.address)
    except evm_service.InvalidEvmAddress as exc:
        raise _bad_request(exc) from exc
    return EvmNonceResponse(
        address=evm_service.normalize_address(payload.address),
        nonce=nonce,
        message=message,
        expires_at=expires_at,
    )


@router.post("/link", response_model=EvmLinkStatus)
async def evm_link(
    data: EvmLinkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvmLinkStatus:
    """Bind the signed EVM address to the authenticated account."""
    try:
        address = evm_service.verify_signature(data.address, data.message, data.signature)
    except (
        evm_service.NonceNotFound,
        evm_service.MessageMismatch,
        evm_service.InvalidSignature,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except evm_service.InvalidEvmAddress as exc:
        raise _bad_request(exc) from exc

    try:
        await evm_service.link_evm_address(db, current_user, address)
    except evm_service.EvmAlreadyLinked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    return EvmLinkStatus(linked=True, evm_address=current_user.evm_address)


@router.delete("/link", status_code=status.HTTP_204_NO_CONTENT)
async def evm_unlink(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await evm_service.unlink_evm_address(db, current_user)


@router.post("/login", response_model=TokenResponse)
async def evm_login(
    data: EvmLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Sign in with an EVM wallet, resolving to the linked etornie account."""
    try:
        address = evm_service.verify_signature(data.address, data.message, data.signature)
    except (
        evm_service.NonceNotFound,
        evm_service.MessageMismatch,
        evm_service.InvalidSignature,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except evm_service.InvalidEvmAddress as exc:
        raise _bad_request(exc) from exc

    user = await evm_service.get_user_by_evm(db, address)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "This EVM wallet is not linked to any Etornie account. "
                "Sign in with your existing account and link it first."
            ),
        )

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )

"""Public partner Q&A API.

``POST /api/v1/chat`` is answer-only: it forwards the question to
EtornieGPT and returns the answer. No agent actions (filings, attestations,
payments) are reachable here, and there is no x402 — it is a plain
question/answer surface for trusted partner platforms, authenticated by an
API key.

Key lifecycle (mint / list / revoke) lives under ``/admin/api-keys`` and is
restricted to admin users.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.etorniegpt.service import ask_etorniegpt
from app.public_api.models import ApiKey
from app.public_api.schemas import (
    ApiKeyCreatedResponse,
    ApiKeyInfo,
    CreateApiKeyRequest,
    PublicChatRequest,
    PublicChatResponse,
)
from app.public_api.security import generate_api_key, require_api_key
from app.users.models import User, UserRole

router = APIRouter(tags=["public-api"])


@router.post("/api/v1/chat", response_model=PublicChatResponse)
async def public_chat(
    data: PublicChatRequest,
    api_key: ApiKey = Depends(require_api_key),
) -> PublicChatResponse:
    """Answer a question via EtornieGPT (answer-only, no actions, no payment)."""
    result = await ask_etorniegpt(data.question, language=data.language)
    return PublicChatResponse(
        answer=result["answer"],
        country_detected=result.get("country_detected"),
        model=result["model"],
    )


@router.post(
    "/admin/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    data: CreateApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
) -> ApiKeyCreatedResponse:
    """Mint a partner API key. The plaintext is returned only in this response."""
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        key_hash=key_hash,
        label=data.label,
        rate_limit_per_minute=data.rate_limit_per_minute,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    return ApiKeyCreatedResponse(
        id=api_key.id,
        label=api_key.label,
        api_key=raw_key,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
    )


@router.get("/admin/api-keys", response_model=list[ApiKeyInfo])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
) -> list[ApiKey]:
    """List all partner keys (never exposes the plaintext or the hash)."""
    rows = await db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return list(rows)


@router.delete(
    "/admin/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
) -> Response:
    """Revoke a key (soft delete — sets is_active=false so it stops working)."""
    api_key = await db.get(ApiKey, key_id)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    api_key.is_active = False
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

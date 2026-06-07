"""Calendar subscription endpoints.

The feed itself is public but token-gated (calendar apps cannot send a
bearer token); the management endpoints are authenticated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.calendar import service
from app.database import get_db
from app.users.models import User

router = APIRouter(prefix="/calendar", tags=["calendar"])


class FeedStatus(BaseModel):
    enabled: bool
    url: str | None = None


@router.get("/feed/{token}.ics")
async def get_calendar_feed(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Public, token-gated iCalendar feed of the user's IP deadlines.

    Unauthenticated by design — the unguessable token identifies the
    subject so calendar clients (Google/Outlook/Apple) can subscribe.
    """
    user = await service.get_user_by_feed_token(db, token)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar feed not found.",
        )

    body = await service.build_feed(db, user)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="etornie-deadlines.ics"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/feed", response_model=FeedStatus)
async def get_feed_status(
    current_user: User = Depends(get_current_user),
) -> FeedStatus:
    token = current_user.calendar_feed_token
    return FeedStatus(
        enabled=bool(token),
        url=service.feed_url(token) if token else None,
    )


@router.post("/feed", response_model=FeedStatus)
async def enable_feed(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FeedStatus:
    """Enable the feed (create a token on first use) and return its URL."""

    token = await service.ensure_token(db, current_user)
    return FeedStatus(enabled=True, url=service.feed_url(token))


@router.post("/feed/rotate", response_model=FeedStatus)
async def rotate_feed(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FeedStatus:
    """Issue a fresh feed URL, revoking the previous one."""

    token = await service.rotate_token(db, current_user)
    return FeedStatus(enabled=True, url=service.feed_url(token))


@router.delete("/feed", status_code=status.HTTP_204_NO_CONTENT)
async def disable_feed(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Disable the feed and revoke the URL."""

    await service.disable_feed(db, current_user)

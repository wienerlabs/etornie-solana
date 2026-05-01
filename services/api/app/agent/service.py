"""CRUD service for agent sessions and messages."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from together import AsyncTogether

from app.agent.models import AgentMessage, AgentSession, AgentSessionStatus
from app.config import settings
from app.database import async_session

logger = logging.getLogger(__name__)


_TITLE_SYSTEM_PROMPT = (
    "You generate concise session titles for an IP-application chat agent. "
    "Given the user's first message, output ONLY the title (3-6 words, no "
    "quotes, no trailing punctuation, no emoji, no explanation). Match the "
    "language of the user's message."
)
_TITLE_MAX_CHARS = 80
_TITLE_MAX_TOKENS = 32


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str | None = None,
    model: str | None = None,
) -> AgentSession:
    session = AgentSession(
        user_id=user_id,
        title=title,
        model=model or settings.together_agent_model,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def list_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[AgentSession]:
    result = await db.execute(
        select(AgentSession)
        .where(
            and_(
                AgentSession.user_id == user_id,
                AgentSession.deleted_at.is_(None),
            )
        )
        .order_by(AgentSession.last_activity_at.desc())
    )
    return list(result.scalars().all())


async def get_session_for_user(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AgentSession | None:
    result = await db.execute(
        select(AgentSession).where(
            and_(
                AgentSession.id == session_id,
                AgentSession.user_id == user_id,
                AgentSession.deleted_at.is_(None),
            )
        )
    )
    return result.scalar_one_or_none()


async def rename_session(
    db: AsyncSession,
    *,
    session: AgentSession,
    title: str,
) -> AgentSession:
    session.title = title
    await db.flush()
    return session


async def soft_delete_session(
    db: AsyncSession,
    *,
    session: AgentSession,
) -> None:
    session.deleted_at = datetime.now(tz=timezone.utc)
    session.status = AgentSessionStatus.archived
    await db.flush()


async def list_messages(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> list[AgentMessage]:
    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def append_user_message(
    db: AsyncSession,
    *,
    session: AgentSession,
    content: str,
) -> AgentMessage:
    from app.agent.models import AgentMessageRole

    msg = AgentMessage(
        session_id=session.id,
        role=AgentMessageRole.user,
        content=content,
    )
    db.add(msg)
    session.last_activity_at = datetime.now(tz=timezone.utc)
    await db.flush()
    await db.refresh(msg)
    return msg


async def generate_and_apply_session_title(
    db: AsyncSession,
    *,
    session: AgentSession,
    first_user_message: str,
) -> None:
    """Generate a concise title and apply it to the session in-place.

    Called inline before the endpoint returns. The session ORM row is
    mutated; the caller is responsible for the commit (the request's
    yield-based DB dependency handles it). This avoids the race that
    arises when a background task mutates the same row concurrently.

    Failures are logged but never raised — a missing title is harmless
    and the user can rename manually. We still attribute the title's
    tokens to the session counters via an atomic UPDATE so the value
    survives any later refresh on the same row.
    """
    if not settings.together_api_key:
        logger.warning("Skipping auto-title: TOGETHER_API_KEY not set")
        return
    if session.title:
        return

    client = AsyncTogether(api_key=settings.together_api_key)
    try:
        response = await client.chat.completions.create(
            model=settings.together_title_model,
            messages=[
                {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": first_user_message},
            ],
            temperature=0.2,
            max_tokens=_TITLE_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto-title generation failed: %s", exc)
        return

    title = (response.choices[0].message.content or "").strip()
    title = title.strip("\"'`").rstrip(".!?")
    if not title:
        return
    if len(title) > _TITLE_MAX_CHARS:
        title = title[:_TITLE_MAX_CHARS].rstrip()

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

    session.title = title
    session.total_input_tokens += input_tokens
    session.total_output_tokens += output_tokens
    await db.flush()

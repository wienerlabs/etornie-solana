import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User, UserRole


async def list_users(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    verification_status: str | None = None,
) -> tuple[list[User], int]:
    """List users, optionally filtered by verification status.

    verification_status values:
      - None: no filter
      - "pending": role=lawyer AND is_verified=false
      - "verified": is_verified=true
      - "unverified": is_verified=false
    """
    stmt = select(User)
    count_stmt = select(func.count(User.id))

    if verification_status == "pending":
        stmt = stmt.where(User.role == UserRole.lawyer, User.is_verified.is_(False))
        count_stmt = count_stmt.where(
            User.role == UserRole.lawyer, User.is_verified.is_(False)
        )
    elif verification_status == "verified":
        stmt = stmt.where(User.is_verified.is_(True))
        count_stmt = count_stmt.where(User.is_verified.is_(True))
    elif verification_status == "unverified":
        stmt = stmt.where(User.is_verified.is_(False))
        count_stmt = count_stmt.where(User.is_verified.is_(False))

    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        stmt.offset(skip).limit(limit).order_by(User.created_at.desc())
    )
    users = list(result.scalars().all())
    return users, total


async def set_verification_status(
    db: AsyncSession,
    user: User,
    is_verified: bool,
) -> User:
    user.is_verified = is_verified
    await db.flush()
    await db.refresh(user)
    return user


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def update_user(
    db: AsyncSession,
    user: User,
    **kwargs: object,
) -> User:
    for key, value in kwargs.items():
        if value is not None:
            setattr(user, key, value)
    await db.flush()
    await db.refresh(user)
    return user


async def soft_delete_user(db: AsyncSession, user: User) -> User:
    user.is_active = False
    await db.flush()
    await db.refresh(user)
    return user

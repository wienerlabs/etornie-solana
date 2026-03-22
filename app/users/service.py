import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User


async def list_users(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[User], int]:
    count_result = await db.execute(select(func.count(User.id)))
    total = count_result.scalar_one()

    result = await db.execute(
        select(User).offset(skip).limit(limit).order_by(User.created_at.desc())
    )
    users = list(result.scalars().all())
    return users, total


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

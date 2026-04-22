import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.users.models import User, UserRole
from app.users.schemas import UserListResponse, UserResponse, UserUpdate
from app.users.service import get_user, list_users, soft_delete_user, update_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserListResponse)
async def list_users_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> UserListResponse:
    """List all users (admin only)."""
    users, total = await list_users(db, skip=skip, limit=limit)
    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in users],
        total=total,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Get user detail. Admin can view any user; others can only view themselves."""
    if current_user.role != UserRole.admin and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own profile",
        )

    user = await get_user(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user_endpoint(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Update a user. Admin can update any user; others can update themselves (except role)."""
    if current_user.role != UserRole.admin and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own profile",
        )

    # Non-admins cannot change roles or active status
    if current_user.role != UserRole.admin:
        if data.role is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change user roles",
            )
        if data.is_active is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change active status",
            )

    user = await get_user(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    update_data = data.model_dump(exclude_unset=True)
    user = await update_user(db, user, **update_data)
    return user


@router.delete("/{user_id}", response_model=UserResponse)
async def delete_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> User:
    """Soft-delete a user (admin only)."""
    user = await get_user(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user = await soft_delete_user(db, user)
    return user

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.auth.email_verification import (
    generate_code,
    send_verification_email,
    store_pending,
    verify_code,
)
from app.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    VerifyCodeRequest,
)
from app.auth.service import (
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_by_id,
)
from app.auth.utils import create_access_token, create_refresh_token, decode_token
from app.database import get_db
from app.users.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Register a new user with any role (public endpoint).

    All roles (admin, lawyer, client) can self-register.
    """
    existing = await get_user_by_email(db, data.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await create_user(
        db,
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role=data.role,
        phone=data.phone,
    )
    return user


@router.post("/register/request")
async def register_request(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Step 1: Request email verification for registration.

    Generates a 6-digit code, stores pending verification data,
    and sends the code via EmailJS.
    """
    existing = await get_user_by_email(db, data.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    code = generate_code()
    registration_data = {
        "email": data.email,
        "password": data.password,
        "full_name": data.full_name,
        "phone": data.phone,
        "role": data.role.value,
    }
    store_pending(data.email, code, registration_data)

    try:
        sent = await send_verification_email(data.email, data.full_name, code)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email",
        )

    if not sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email",
        )

    return {"message": "Verification code sent to your email"}


@router.post(
    "/register/verify",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_verify(
    data: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Step 2: Verify the code and create the user account."""
    registration_data = verify_code(data.email, data.code)
    if registration_data is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )

    user = await create_user(
        db,
        email=registration_data["email"],
        password=registration_data["password"],
        full_name=registration_data["full_name"],
        role=UserRole(registration_data["role"]),
        phone=registration_data["phone"],
    )
    return user


@router.post(
    "/register/admin",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_admin(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> User:
    """Register a user with any role (admin-only)."""
    existing = await get_user_by_email(db, data.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await create_user(
        db,
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role=data.role,
        phone=data.phone,
    )
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await authenticate_user(db, data.email, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        payload = decode_token(data.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user

import logging
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
    LoginResponse,
    MfaLoginRequest,
    PublicRegisterRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    TwoFactorDisableRequest,
    TwoFactorEnableRequest,
    TwoFactorEnableResponse,
    TwoFactorEnrollResponse,
    TwoFactorStatusResponse,
    UserResponse,
    VerifyCodeRequest,
)
from app.auth.service import (
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_by_id,
)
from app.auth import totp_service
from app.auth.totp_service import TotpError
from app.auth.utils import (
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_token,
)
from app.cases.guest_linking import link_guest_cases
from app.database import get_db
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: PublicRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Register a new user (public endpoint).

    Only the client role can self-register; admin must be provisioned
    via /auth/register/admin by an existing admin. The lawyer role was
    retired on 2026-05-02 (docs/REMOVED_LAWYER_LAYER.md).
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

    try:
        linked = await link_guest_cases(db, user)
        if linked > 0:
            logger.info("Linked %d guest cases to new user %s", linked, user.email)
    except Exception as exc:
        logger.warning("Failed to link guest cases: %s", exc)

    return user


@router.post("/register/request")
async def register_request(
    data: PublicRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Step 1: Request email verification for registration.

    Generates a 6-digit code, stores pending verification data,
    and emails the code via the server-side SMTP transport.
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

    try:
        linked = await link_guest_cases(db, user)
        if linked > 0:
            logger.info("Linked %d guest cases to new user %s", linked, user.email)
    except Exception as exc:
        logger.warning("Failed to link guest cases: %s", exc)

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

    try:
        linked = await link_guest_cases(db, user)
        if linked > 0:
            logger.info("Linked %d guest cases to new user %s", linked, user.email)
    except Exception as exc:
        logger.warning("Failed to link guest cases: %s", exc)

    return user


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    user = await authenticate_user(db, data.email, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.totp_enabled:
        # Password is correct but the account is 2FA-protected: hand back
        # a short-lived challenge token instead of access tokens. The
        # client completes the second factor at /auth/login/mfa.
        return LoginResponse(
            mfa_required=True,
            mfa_token=create_mfa_token(str(user.id)),
        )

    return LoginResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/login/mfa", response_model=TokenResponse)
async def login_mfa(
    data: MfaLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Complete a 2FA login by exchanging the challenge token + code."""

    try:
        payload = decode_token(data.mfa_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication session",
        )

    if payload.get("type") != "mfa":
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

    if not await totp_service.verify_second_factor(db, user, data.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication code",
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


@router.get("/2fa/status", response_model=TwoFactorStatusResponse)
async def two_factor_status(
    current_user: User = Depends(get_current_user),
) -> TwoFactorStatusResponse:
    return TwoFactorStatusResponse(
        enabled=current_user.totp_enabled,
        required=current_user.mfa_setup_required,
        recovery_codes_remaining=totp_service.recovery_codes_remaining(current_user),
    )


@router.post("/2fa/enroll", response_model=TwoFactorEnrollResponse)
async def two_factor_enroll(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TwoFactorEnrollResponse:
    """Start enrollment: mint a secret and return its QR / otpauth URI."""

    try:
        result = await totp_service.begin_enrollment(db, current_user)
    except TotpError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return TwoFactorEnrollResponse(
        secret=result.secret,
        otpauth_uri=result.otpauth_uri,
        qr_data_url=result.qr_data_url,
    )


@router.post("/2fa/enable", response_model=TwoFactorEnableResponse)
async def two_factor_enable(
    data: TwoFactorEnableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TwoFactorEnableResponse:
    """Confirm possession of the secret and turn 2FA on."""

    try:
        recovery_codes = await totp_service.enable(db, current_user, data.code)
    except TotpError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return TwoFactorEnableResponse(recovery_codes=recovery_codes)


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def two_factor_disable(
    data: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Turn 2FA off after proving possession (TOTP or recovery code)."""

    try:
        await totp_service.disable(db, current_user, data.code)
    except TotpError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

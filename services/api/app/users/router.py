import json
import os
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.cases.models import Case
from app.compliance.data_export import build_user_export
from app.config import settings
from app.database import get_db
from app.services.ukipo.models import UKIPOSubmission
from app.users.models import User, UserRole
from app.users.schemas import UserListResponse, UserResponse, UserUpdate
from app.users.service import get_user, list_users, soft_delete_user, update_user

router = APIRouter(prefix="/users", tags=["users"])

_AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
_AVATAR_ALLOWED_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


@router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Upload (or replace) the authenticated user's profile picture.

    The bytes land on disk under ``<upload_dir>/avatars/<user_id>.<ext>``
    so the file size never bloats the users row. The DB only stores the
    path and the content-type; ``GET /users/{id}/avatar`` serves the
    file back.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    if len(raw) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"avatar exceeds {_AVATAR_MAX_BYTES // (1024 * 1024)} MiB limit",
        )
    mime = (file.content_type or "").lower().strip()
    ext = _AVATAR_ALLOWED_MIME.get(mime)
    if ext is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Unsupported avatar mime type. Allowed: "
            + ", ".join(sorted(_AVATAR_ALLOWED_MIME.keys())),
        )

    # Store the bytes in the DB so the avatar survives container restarts and
    # redeploys (the previous on-disk location was ephemeral). Clean up any
    # legacy on-disk file left over from before this change.
    if current_user.avatar_path and os.path.isfile(current_user.avatar_path):
        try:
            os.remove(current_user.avatar_path)
        except OSError:
            pass

    current_user.avatar_data = raw
    current_user.avatar_mime = mime
    current_user.avatar_path = None
    await db.flush()
    await db.refresh(current_user)
    return current_user


@router.delete("/me/avatar", response_model=UserResponse)
async def delete_my_avatar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Remove the authenticated user's profile picture (file + columns)."""
    if current_user.avatar_path and os.path.isfile(current_user.avatar_path):
        try:
            os.remove(current_user.avatar_path)
        except OSError:
            pass
    current_user.avatar_path = None
    current_user.avatar_mime = None
    current_user.avatar_data = None
    await db.flush()
    await db.refresh(current_user)
    return current_user


@router.get("/{user_id}/avatar")
async def get_user_avatar(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Stream a user's profile picture.

    Authenticated by the standard bearer token; admins can fetch any
    user's avatar, every other caller can only fetch their own. Bytes are
    served from the DB (avatar_data); a legacy on-disk avatar is served as a
    fallback while one still exists.
    """
    if current_user.role != UserRole.admin and current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    row = (
        await db.execute(
            select(User.avatar_data, User.avatar_mime, User.avatar_path).where(
                User.id == user_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    avatar_data, avatar_mime, avatar_path = row
    media_type = avatar_mime or "application/octet-stream"
    if avatar_data:
        return Response(content=avatar_data, media_type=media_type)
    if avatar_path and os.path.isfile(avatar_path):
        return FileResponse(path=avatar_path, media_type=media_type)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "no avatar uploaded")


@router.get("/me/timeline")
async def get_my_timeline(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cross-jurisdiction filing timeline for the authenticated user.

    Returns every case the caller owns (as ``client_id``) plus the
    latest UKIPO submission attached to each, with all the on-chain
    references (attestation, NFT, payment, compliance) the profile
    page needs to render its history view. Admins see every case.
    """
    case_query = select(Case)
    if current_user.role == UserRole.client:
        case_query = case_query.where(Case.client_id == current_user.id)
    case_query = case_query.order_by(Case.created_at.desc())
    cases = (await db.execute(case_query)).scalars().all()

    items: list[dict[str, Any]] = []
    for case in cases:
        sub_row = (
            await db.execute(
                select(UKIPOSubmission)
                .where(UKIPOSubmission.case_id == case.id)
                .order_by(UKIPOSubmission.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        latest_filing: dict[str, Any] | None = None
        if sub_row is not None:
            latest_filing = {
                "jurisdiction": "UKIPO",
                "submission_id": str(sub_row.id),
                "status": sub_row.status.value,
                "current_step": sub_row.current_step,
                "error_step": sub_row.error_step,
                "error_message": sub_row.error_message,
                "ipo_reference": sub_row.ipo_reference,
                "ipo_application_url": sub_row.ipo_application_url,
                "mark_text": sub_row.mark_text,
                "mark_type": sub_row.mark_type.value,
                "owner_company_name": sub_row.owner_company_name,
                "payment_tx": sub_row.solana_payment_tx,
                "payment_lamports": sub_row.solana_payment_lamports,
                "payment_at": (
                    sub_row.solana_payment_at.isoformat()
                    if sub_row.solana_payment_at
                    else None
                ),
                "compliance_tx": sub_row.solana_compliance_tx,
                "compliance_pda": sub_row.solana_compliance_pda,
                "query_hash_hex": sub_row.solana_query_hash_hex,
                "commitment_hex": sub_row.solana_commitment_hex,
                "started_at": (
                    sub_row.started_at.isoformat() if sub_row.started_at else None
                ),
                "finished_at": (
                    sub_row.finished_at.isoformat() if sub_row.finished_at else None
                ),
            }

        items.append(
            {
                "case_id": str(case.id),
                "case_number": case.case_number,
                "title": case.title,
                "case_type": case.case_type.value,
                "status": case.status.value,
                "jurisdiction": case.jurisdiction,
                "nice_classes": case.nice_classes,
                "created_at": case.created_at.isoformat(),
                "updated_at": case.updated_at.isoformat(),
                "client_wallet": case.client_wallet,
                "attestation_tx": case.attestation_tx,
                "attestation_pda": case.attestation_pda,
                "nft": {
                    "state": case.nft_state.value,
                    "mint": case.nft_mint,
                    "setup_tx": case.nft_setup_tx,
                    "mint_tx": case.nft_mint_tx,
                    "burn_tx": case.nft_burn_tx,
                    "burned_at": (
                        case.nft_burned_at.isoformat() if case.nft_burned_at else None
                    ),
                },
                "latest_filing": latest_filing,
            }
        )

    return {
        "user_id": str(current_user.id),
        "count": len(items),
        "items": items,
    }


_DATA_EXPORT_FORMATS = {
    "json": ("application/json", "json"),
    "pdf": ("application/pdf", "pdf"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
}


@router.get("/me/export")
async def export_my_data(
    format: str = Query("json", pattern="^(json|pdf|docx|xlsx)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Export all personal data of the authenticated user (GDPR Art. 20).

    JSON is the canonical structured, machine-readable format the right
    to data portability requires; ``format=pdf|docx|xlsx`` returns the
    same data as a branded human-readable document. The caller can only
    export their own data — the bearer token identifies the subject, so
    there is no user-id path parameter to authorise against.
    """
    payload = await build_user_export(db, current_user)
    media_type, ext = _DATA_EXPORT_FORMATS[format]
    filename = f"etornie-data-export-{current_user.id}.{ext}"

    if format == "json":
        body: bytes | str = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        # Heavy rendering deps (reportlab, python-docx, openpyxl) are
        # imported lazily so the users module stays cheap to import.
        from app.compliance.data_export_render import (
            render_docx,
            render_pdf,
            render_xlsx,
        )

        if format == "pdf":
            body = render_pdf(payload)
        elif format == "docx":
            body = render_docx(payload)
        else:
            body = render_xlsx(payload)

    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


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

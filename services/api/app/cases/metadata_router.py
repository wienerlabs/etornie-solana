"""Dynamic Token-2022 metadata endpoint for Case NFTs.

Phantom and other Solana wallets fetch the URI set in the mint's
TokenMetadata extension when rendering the NFT. Because our URI points
here (backend-served), we regenerate the JSON from live DB state on
every request — status badges update without any on-chain tx.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.cases.service import build_case_metadata_json, get_case
from app.database import get_db

router = APIRouter(tags=["case-metadata"])


def _parse_case_id_from_filename(filename: str) -> uuid.UUID:
    """Accept <hex>.json or <hex>.png paths and return the UUID."""
    base = filename.split(".", 1)[0]
    try:
        return uuid.UUID(hex=base)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "case_id must be a UUID hex"
        ) from exc


@router.get("/case-metadata/{filename}")
async def get_case_metadata(
    filename: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return dynamic Token-2022 metadata for a case NFT.

    No auth: the URI is embedded in the on-chain mint metadata and must
    be publicly fetchable for wallet rendering. Content is reconstructed
    from non-sensitive case fields only (case_number, status, type).
    """
    case_id = _parse_case_id_from_filename(filename)
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    return build_case_metadata_json(case)

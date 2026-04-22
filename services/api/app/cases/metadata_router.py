"""Dynamic Token-2022 metadata endpoint for Case NFTs.

Phantom and other Solana wallets fetch the URI set in the mint's
TokenMetadata extension when rendering the NFT. Because our URI points
here (backend-served), we regenerate the JSON from live DB state on
every request — status badges update without any on-chain tx.

Also serves a dynamically rendered SVG card (/case-metadata/{id}.svg)
so the wallet has something visual to display.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseNftState, CaseStatus
from app.cases.service import build_case_metadata_json, get_case
from app.database import get_db

router = APIRouter(tags=["case-metadata"])


def _parse_case_id_from_filename(filename: str) -> tuple[uuid.UUID, str]:
    """Accept ``<hex>.json`` / ``<hex>.svg`` / ``<hex>.png`` and return (uuid, ext)."""
    if "." not in filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "filename must have an extension"
        )
    base, ext = filename.rsplit(".", 1)
    try:
        return uuid.UUID(hex=base), ext.lower()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "case_id must be a UUID hex"
        ) from exc


_STATUS_COLOR: dict[CaseStatus, str] = {
    CaseStatus.open: "#22c55e",
    CaseStatus.in_progress: "#3b82f6",
    CaseStatus.under_review: "#eab308",
    CaseStatus.closed: "#ef4444",
}

_NFT_STATE_LABEL: dict[CaseNftState, str] = {
    CaseNftState.none: "Not attested",
    CaseNftState.pending_claim: "Ready to claim",
    CaseNftState.minted: "Soul-bound",
    CaseNftState.burned: "Burned",
}


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _render_case_svg(case: Case) -> str:
    """Compose a 512×512 SVG card for the case NFT."""
    badge = _STATUS_COLOR.get(case.status, "#6b7280")
    state_label = _NFT_STATE_LABEL.get(case.nft_state, "—")
    title = _xml_escape(case.title[:32] + ("…" if len(case.title) > 32 else ""))
    case_number = _xml_escape(case.case_number)
    case_type = _xml_escape(case.case_type.value.title())
    status_label = _xml_escape(case.status.value.replace("_", " ").title())
    jurisdiction = _xml_escape(case.jurisdiction or "—")[:40]

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e293b"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)" rx="24"/>
  <rect x="24" y="24" width="464" height="464" fill="none" stroke="#334155" stroke-width="1" rx="16"/>

  <text x="40" y="72" font-family="system-ui, -apple-system, Helvetica" font-size="14" fill="#94a3b8" letter-spacing="2">ETORNIE · SOUL-BOUND CASE NFT</text>

  <text x="40" y="130" font-family="system-ui, -apple-system, Helvetica" font-weight="700" font-size="36" fill="#f8fafc">{case_number}</text>

  <text x="40" y="176" font-family="system-ui, -apple-system, Helvetica" font-size="20" fill="#cbd5e1">{title}</text>

  <g transform="translate(40, 220)">
    <rect width="180" height="32" fill="{badge}" opacity="0.15" rx="16"/>
    <circle cx="20" cy="16" r="5" fill="{badge}"/>
    <text x="36" y="22" font-family="system-ui, -apple-system, Helvetica" font-size="13" fill="{badge}" font-weight="600">{status_label}</text>
  </g>

  <g transform="translate(40, 300)">
    <text font-family="system-ui, -apple-system, Helvetica" font-size="11" fill="#64748b" letter-spacing="1.5">CASE TYPE</text>
    <text y="24" font-family="system-ui, -apple-system, Helvetica" font-size="18" fill="#e2e8f0" font-weight="500">{case_type}</text>
  </g>

  <g transform="translate(260, 300)">
    <text font-family="system-ui, -apple-system, Helvetica" font-size="11" fill="#64748b" letter-spacing="1.5">JURISDICTION</text>
    <text y="24" font-family="system-ui, -apple-system, Helvetica" font-size="18" fill="#e2e8f0" font-weight="500">{jurisdiction}</text>
  </g>

  <g transform="translate(40, 380)">
    <text font-family="system-ui, -apple-system, Helvetica" font-size="11" fill="#64748b" letter-spacing="1.5">NFT STATE</text>
    <text y="24" font-family="system-ui, -apple-system, Helvetica" font-size="18" fill="#a5b4fc" font-weight="500">{_xml_escape(state_label)}</text>
  </g>

  <g transform="translate(40, 452)">
    <rect width="14" height="14" fill="#6366f1" rx="3"/>
    <text x="24" y="12" font-family="system-ui, -apple-system, Helvetica" font-size="12" fill="#94a3b8">Token-2022 · Frozen · Light Protocol</text>
  </g>
</svg>"""


@router.get("/case-metadata/{filename}")
async def get_case_metadata(
    filename: str,
    db: AsyncSession = Depends(get_db),
):
    """Return dynamic Token-2022 metadata JSON or SVG image for a case NFT.

    No auth: the URI is embedded in the on-chain mint metadata and must
    be publicly fetchable for wallet rendering. Content is reconstructed
    from non-sensitive case fields only (case_number, status, type).
    """
    case_id, ext = _parse_case_id_from_filename(filename)
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")

    if ext == "json":
        return build_case_metadata_json(case)
    if ext in ("svg", "png"):
        # Both extensions serve the same SVG body; some wallets fetch .png
        # blindly, and SVG renders fine when Content-Type is set.
        return Response(
            content=_render_case_svg(case),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=30"},
        )
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST, f"unsupported extension: {ext}"
    )

"""Helius transaction webhook → on-chain state reconciliation (#19).

Helius POSTs the raw transactions touching our three program IDs here; we
decode the Anchor events from each tx's log messages and reconcile the
corresponding DB rows (see :mod:`app.solana.events`). This closes the gap where
a dropped confirmation or a slot rollback left the DB out of sync with the
chain.

Security: fail-closed. The endpoint rejects every call unless the webhook's
Authorization header matches ``HELIUS_WEBHOOK_AUTH``, so it is inert until
configured. Authorised calls always return 200 — a single malformed tx is
logged and skipped rather than 500'd, so Helius does not enter a retry storm.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import settings
from app.database import get_db
from app.solana.events import (
    ReconcileResult,
    decode_log_events,
    reconcile_events,
    reconciliation_metrics,
)
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/solana", tags=["solana"])


def _extract_tx(tx: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Pull ``(signature, log_messages)`` out of one Helius raw-webhook tx.

    Skips transactions that failed on-chain (``meta.err`` set) — state is never
    reconciled from a tx the cluster rejected.
    """
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return None, []
    logs = meta.get("logMessages") or tx.get("logs") or []
    txn = tx.get("transaction") or {}
    signatures = txn.get("signatures") if isinstance(txn, dict) else None
    signature = (signatures[0] if signatures else None) or tx.get("signature")
    return signature, logs


@router.post("/webhooks/helius", status_code=status.HTTP_200_OK)
async def helius_webhook(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    """Receive a Helius webhook batch and reconcile every recognised event."""
    expected = settings.helius_webhook_auth
    provided = request.headers.get("authorization", "")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid JSON body"
        ) from None

    transactions = payload if isinstance(payload, list) else [payload]
    total = ReconcileResult()
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        signature, logs = _extract_tx(tx)
        if not signature or not logs:
            continue
        events = decode_log_events(logs)
        if not events:
            continue
        res = await reconcile_events(db, events, signature)
        total.received += res.received
        total.reconciled += res.reconciled
        total.skipped += res.skipped
        total.failed += res.failed

    logger.info(
        "helius webhook: txs=%d received=%d reconciled=%d skipped=%d failed=%d",
        len(transactions),
        total.received,
        total.reconciled,
        total.skipped,
        total.failed,
        extra={"reconcile_metrics": reconciliation_metrics()},
    )
    return {
        "received": total.received,
        "reconciled": total.reconciled,
        "skipped": total.skipped,
        "failed": total.failed,
    }


@router.get("/webhooks/helius/metrics")
async def helius_webhook_metrics(
    _admin: User = Depends(require_role(UserRole.admin)),
) -> dict[str, dict[str, int]]:
    """Cumulative per-program reconciliation counters (admin only)."""
    return reconciliation_metrics()

"""BRAID-internal endpoints.

Thin reasoning-side endpoints consumed by the OpenServ BRAID agent in
``services/braid``. These wrap canonical Etornie logic (e.g. on-chain
payment verification) so the agent does not duplicate domain code.

Auth: every endpoint requires an ``X-Braid-Auth`` header that matches
``settings.braid_internal_token``. If the token is unset, the entire
router refuses requests (fail-closed). The token is shared between this
service and ``services/braid/.env``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from together import Together

from app.braid.models import BraidDecision
from app.config import settings
from app.database import get_db
from app.solana.client import (
    SolanaClientError,
    derive_file_ownership_record_pda,
    verify_payment_tx,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/braid", tags=["braid"])


def _check_auth(x_braid_auth: str | None) -> None:
    if not settings.braid_internal_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "braid endpoints disabled (BRAID_INTERNAL_TOKEN unset)",
        )
    if x_braid_auth != settings.braid_internal_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing X-Braid-Auth header",
        )


class VerifyX402Request(BaseModel):
    signature: str = Field(
        ..., description="Solana transaction signature of the payment to verify"
    )
    expected_memo: str = Field(
        ...,
        description=(
            "Memo string the payment must carry; typically "
            "base58(sha256(query_hash || commitment))"
        ),
    )
    min_lamports: int | None = Field(
        default=None,
        description="Override min lamports; defaults to platform setting",
    )
    recipient_vault: str | None = Field(
        default=None,
        description="Override recipient vault pubkey; defaults to platform setting",
    )


class VerifyX402Response(BaseModel):
    verified: bool
    signature: str
    recipient_vault: str
    min_lamports_required: int
    expected_memo: str
    error: str | None = None


@router.post(
    "/verify-x402-payment",
    response_model=VerifyX402Response,
    summary="Verify an x402 SOL micropayment for the EtornieGPT flow",
)
async def verify_x402_payment(
    body: VerifyX402Request,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> VerifyX402Response:
    """Verify a Solana payment tx against the EtornieGPT vault.

    Always returns ``HTTP 200`` so the BRAID agent can reason over the
    structured outcome (success or auditable failure). Auth/config errors
    use proper HTTP status codes.
    """
    _check_auth(x_braid_auth)

    vault_str = body.recipient_vault or settings.etorniegpt_payment_vault
    if not vault_str:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "etorniegpt payment vault not configured",
        )

    min_lamports = body.min_lamports or settings.etorniegpt_payment_lamports

    try:
        recipient = Pubkey.from_string(vault_str)
    except Exception as exc:  # noqa: BLE001 - normalize all parse errors
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid recipient_vault pubkey: {exc}",
        ) from exc

    try:
        await verify_payment_tx(
            signature=body.signature,
            expected_recipient=recipient,
            min_lamports=min_lamports,
            expected_memo=body.expected_memo,
        )
    except SolanaClientError as exc:
        logger.info(
            "braid verify_x402 failed sig=%s reason=%s", body.signature, exc
        )
        return VerifyX402Response(
            verified=False,
            signature=body.signature,
            recipient_vault=vault_str,
            min_lamports_required=min_lamports,
            expected_memo=body.expected_memo,
            error=str(exc),
        )

    return VerifyX402Response(
        verified=True,
        signature=body.signature,
        recipient_vault=vault_str,
        min_lamports_required=min_lamports,
        expected_memo=body.expected_memo,
    )


# ────────────────────────────────────────────────────────────────────
# ZK file-ownership verification
# ────────────────────────────────────────────────────────────────────


class VerifyZkFileOwnershipRequest(BaseModel):
    user_wallet: str = Field(
        ...,
        min_length=32,
        max_length=44,
        description="Base58 pubkey of the claimed file owner",
    )
    file_hash_hex: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Hex-encoded 32-byte SHA-256 digest of the file",
    )


class VerifyZkFileOwnershipResponse(BaseModel):
    verified: bool
    user_wallet: str
    file_hash_hex: str
    file_ownership_record: str
    explorer_url: str
    account_size_bytes: int | None = None
    error: str | None = None


def _decline(
    body: VerifyZkFileOwnershipRequest,
    *,
    pda: str = "",
    explorer_url: str = "",
    account_size: int | None = None,
    error: str,
) -> VerifyZkFileOwnershipResponse:
    return VerifyZkFileOwnershipResponse(
        verified=False,
        user_wallet=body.user_wallet,
        file_hash_hex=body.file_hash_hex,
        file_ownership_record=pda,
        explorer_url=explorer_url,
        account_size_bytes=account_size,
        error=error,
    )


@router.post(
    "/verify-zk-file-ownership",
    response_model=VerifyZkFileOwnershipResponse,
    summary="Verify a file_ownership ZK proof exists on-chain",
)
async def verify_zk_file_ownership(
    body: VerifyZkFileOwnershipRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> VerifyZkFileOwnershipResponse:
    """Check whether a FileOwnershipRecord PDA exists on-chain for the
    given (user, file_hash) pair.

    Returns ``HTTP 200`` with a structured outcome in all decision paths
    (verified, no proof on-chain, malformed input, RPC error) so the
    BRAID agent can reason over auditable failures. Auth/config errors
    use proper HTTP status codes.
    """
    _check_auth(x_braid_auth)

    try:
        user = Pubkey.from_string(body.user_wallet)
    except Exception as exc:  # noqa: BLE001
        return _decline(body, error=f"invalid user_wallet pubkey: {exc}")

    try:
        file_hash = bytes.fromhex(body.file_hash_hex)
    except ValueError as exc:
        return _decline(body, error=f"file_hash_hex is not hex: {exc}")
    if len(file_hash) != 32:
        return _decline(
            body,
            error=f"file_hash must decode to 32 bytes, got {len(file_hash)}",
        )

    pda, _bump = derive_file_ownership_record_pda(user, file_hash)
    pda_str = str(pda)
    explorer_url = (
        f"https://explorer.solana.com/address/{pda_str}?cluster=devnet"
    )

    try:
        async with AsyncClient(settings.solana_cluster_url) as rpc:
            resp = await rpc.get_account_info(pda, commitment=Confirmed)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "braid verify_zk_file_ownership: RPC error: %s", exc
        )
        return _decline(
            body,
            pda=pda_str,
            explorer_url=explorer_url,
            error=f"solana RPC unreachable: {exc}",
        )

    if resp.value is None:
        return _decline(
            body,
            pda=pda_str,
            explorer_url=explorer_url,
            error=(
                "no FileOwnershipRecord on-chain for this (user_wallet, "
                "file_hash) — proof not submitted, or pair is invalid"
            ),
        )

    account_size = len(bytes(resp.value.data))
    if account_size < 8:
        return _decline(
            body,
            pda=pda_str,
            explorer_url=explorer_url,
            account_size=account_size,
            error=(
                "account exists but smaller than Anchor discriminator "
                "(8 bytes) — likely not a FileOwnershipRecord"
            ),
        )

    return VerifyZkFileOwnershipResponse(
        verified=True,
        user_wallet=body.user_wallet,
        file_hash_hex=body.file_hash_hex,
        file_ownership_record=pda_str,
        explorer_url=explorer_url,
        account_size_bytes=account_size,
    )


# ────────────────────────────────────────────────────────────────────
# Audit trail — BRAID decisions
# ────────────────────────────────────────────────────────────────────


class CreateDecisionRequest(BaseModel):
    workspace_id: str = Field(..., max_length=64)
    thread_id: int
    agent_id: int
    agent_name: str | None = Field(default=None, max_length=128)
    capability_name: str = Field(..., max_length=128)
    args: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    user_message: str | None = None
    started_at: datetime
    completed_at: datetime
    duration_ms: int


class DecisionRow(BaseModel):
    id: uuid.UUID
    workspace_id: str
    thread_id: int
    agent_id: int
    agent_name: str | None
    capability_name: str
    args: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    user_message: str | None
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionList(BaseModel):
    items: list[DecisionRow]
    count: int


def _row_to_model(row: BraidDecision) -> DecisionRow:
    return DecisionRow.model_validate(row)


@router.post(
    "/decisions",
    response_model=DecisionRow,
    status_code=status.HTTP_201_CREATED,
    summary="Record a BRAID capability invocation (audit trail write)",
)
async def create_decision(
    body: CreateDecisionRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionRow:
    """Persist one capability invocation. Called by the BRAID agent
    after every wrapped capability finishes, fire-and-forget."""
    _check_auth(x_braid_auth)

    decision = BraidDecision(
        workspace_id=body.workspace_id,
        thread_id=body.thread_id,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        capability_name=body.capability_name,
        args=body.args,
        result=body.result,
        error=body.error,
        user_message=body.user_message,
        started_at=body.started_at,
        completed_at=body.completed_at,
        duration_ms=body.duration_ms,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)
    return _row_to_model(decision)


@router.get(
    "/decisions",
    response_model=DecisionList,
    summary="List BRAID decisions (newest first); filter by workspace, thread, capability",
)
async def list_decisions(
    workspace_id: str | None = Query(default=None, max_length=64),
    thread_id: int | None = Query(default=None),
    capability_name: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=500),
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    _check_auth(x_braid_auth)

    stmt = select(BraidDecision).order_by(desc(BraidDecision.started_at))
    if workspace_id is not None:
        stmt = stmt.where(BraidDecision.workspace_id == workspace_id)
    if thread_id is not None:
        stmt = stmt.where(BraidDecision.thread_id == thread_id)
    if capability_name is not None:
        stmt = stmt.where(BraidDecision.capability_name == capability_name)
    stmt = stmt.limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return DecisionList(
        items=[_row_to_model(r) for r in rows], count=len(rows)
    )


@router.get(
    "/decisions/trace",
    response_model=DecisionList,
    summary="Chronological trace of decisions for one (workspace, thread)",
)
async def get_trace(
    workspace_id: str = Query(..., max_length=64),
    thread_id: int = Query(...),
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionList:
    """Returns the ordered (oldest → newest) chain of BRAID capability
    calls within a single chat thread. This is the reasoning trace a
    regulator/auditor reads to reconstruct how a decision was reached."""
    _check_auth(x_braid_auth)

    stmt = (
        select(BraidDecision)
        .where(BraidDecision.workspace_id == workspace_id)
        .where(BraidDecision.thread_id == thread_id)
        .order_by(BraidDecision.started_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return DecisionList(
        items=[_row_to_model(r) for r in rows], count=len(rows)
    )


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionRow,
    summary="Single decision detail",
)
async def get_decision(
    decision_id: uuid.UUID,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> DecisionRow:
    _check_auth(x_braid_auth)

    row = await db.get(BraidDecision, decision_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"decision {decision_id} not found"
        )
    return _row_to_model(row)


# ────────────────────────────────────────────────────────────────────
# Customer message triage (Together AI gpt-oss-20b)
# ────────────────────────────────────────────────────────────────────

_TRIAGE_MODEL = settings.together_model or "openai/gpt-oss-20b"

_TRIAGE_SYSTEM_PROMPT = """You are the inbound-message triage layer for Etornie, \
a regulated IP filing platform (UKIPO / EUIPO / IP Australia / WIPO).

Your only job: classify ONE incoming customer message (WhatsApp, email, web chat) \
into a structured intent + urgency + entity extraction so it can be routed correctly.

Classification taxonomy (pick exactly one):
- new_filing_request       : user wants to start a new trademark/IP filing
- existing_case_inquiry    : user asks about status of an existing case
- office_response_forwarded: user forwarded a letter/notice from an IP office
- objection_or_dispute     : opposition, third-party challenge, infringement claim
- billing_question         : pricing, refund, invoice, payment issue
- support_request          : technical/account help unrelated to filings
- spam_or_irrelevant       : promotional, off-topic, automated noise
- urgent_legal_deadline    : explicit deadline mentioned that needs immediate action

Urgency levels:
- low      : no time pressure, informational
- medium   : action needed within a few days
- high     : action needed within 24h
- critical : deadline today or already passed, regulator-imposed risk

Entity extraction (set null if not present in the message):
- case_id          : any case/application number (e.g. UK00012345, EUTM018xxxxxxx)
- jurisdiction     : country or office name (UK, EU, AU, WIPO, etc.)
- trademark_name   : the brand / mark name being discussed
- deadline         : ISO date string YYYY-MM-DD if explicitly mentioned

Output rules (read carefully — these are non-negotiable):
1. Output a SINGLE JSON object. Nothing before, nothing after. No markdown \
fences, no commentary, no scratchpad, no "commentary to=assistant" wrappers.
2. The object MUST start with the literal key "classification" whose value \
is the classification string (NOT a boolean). Do not flatten the classification \
into a separate boolean key.
3. confidence: your honest 0..1 estimate of classification correctness.
4. recommended_action: one short sentence (e.g. "route to filing team", \
"respond automatically with status link", "escalate to in-house counsel").
5. escalation_required: true if confidence < 0.6, or urgency is critical, or \
the message implies legal liability (objection, infringement, deadline missed).
6. reasoning: one or two sentences explaining the classification — this is \
written into the audit trail and read by regulators/lawyers later.
7. Never invent entity values. If unsure, leave them null.

Concrete example.
INPUT MESSAGE: "Hi, I'd like to register the trademark FOOBAR in Germany. How much?"
EXPECTED OUTPUT (exactly this shape, with your real values):
{"classification":"new_filing_request","confidence":0.95,"urgency":"low",\
"recommended_action":"route to filing team","detected_entities":\
{"case_id":null,"jurisdiction":"DE","trademark_name":"FOOBAR","deadline":null},\
"reasoning":"User explicitly asks to register a new trademark in Germany and \
asks about cost.","escalation_required":false}"""


_TRIAGE_JSON_SCHEMA_HINT = """{
  "classification": "<one of: new_filing_request | existing_case_inquiry | office_response_forwarded | objection_or_dispute | billing_question | support_request | spam_or_irrelevant | urgent_legal_deadline>",
  "confidence": 0.0,
  "urgency": "<low | medium | high | critical>",
  "recommended_action": "<short sentence>",
  "detected_entities": {
    "case_id": null,
    "jurisdiction": null,
    "trademark_name": null,
    "deadline": null
  },
  "reasoning": "<one or two sentences>",
  "escalation_required": false
}"""


class TriageClassification(str, Enum):
    NEW_FILING_REQUEST = "new_filing_request"
    EXISTING_CASE_INQUIRY = "existing_case_inquiry"
    OFFICE_RESPONSE_FORWARDED = "office_response_forwarded"
    OBJECTION_OR_DISPUTE = "objection_or_dispute"
    BILLING_QUESTION = "billing_question"
    SUPPORT_REQUEST = "support_request"
    SPAM_OR_IRRELEVANT = "spam_or_irrelevant"
    URGENT_LEGAL_DEADLINE = "urgent_legal_deadline"


class TriageUrgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriageEntities(BaseModel):
    case_id: str | None = Field(default=None, max_length=64)
    jurisdiction: str | None = Field(default=None, max_length=64)
    trademark_name: str | None = Field(default=None, max_length=256)
    deadline: str | None = Field(default=None, max_length=32)


class TriageRequest(BaseModel):
    message_text: str = Field(..., min_length=1, max_length=8000)
    channel: Literal["whatsapp", "email", "web_chat", "unknown"] = "unknown"
    sender: str | None = Field(default=None, max_length=256)
    language: str | None = Field(default=None, max_length=16)


class TriageResponse(BaseModel):
    classification: TriageClassification
    confidence: float = Field(ge=0.0, le=1.0)
    urgency: TriageUrgency
    recommended_action: str = Field(..., min_length=1, max_length=512)
    detected_entities: TriageEntities = Field(default_factory=TriageEntities)
    reasoning: str = Field(..., min_length=1, max_length=2000)
    escalation_required: bool
    model: str


def _call_together_sync(
    message_text: str,
    channel: str,
    sender: str | None,
    language: str | None,
) -> str:
    """Blocking Together AI call. Run via asyncio.to_thread from async paths."""
    client = Together(api_key=settings.together_api_key)

    user_payload_lines = [
        f"channel: {channel}",
        f"sender: {sender or 'unknown'}",
        f"language_hint: {language or 'auto'}",
        "",
        "MESSAGE:",
        message_text,
        "",
        "Respond with JSON exactly matching this shape (fill in real values):",
        _TRIAGE_JSON_SCHEMA_HINT,
    ]

    response = client.chat.completions.create(
        model=_TRIAGE_MODEL,
        messages=[
            {"role": "system", "content": _TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_payload_lines)},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1024,
    )

    content = response.choices[0].message.content or ""
    return content


_VALID_CLASSIFICATIONS = {c.value for c in TriageClassification}


def _normalize_triage_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    """Defensively rescue gpt-oss-20b output that drifts from the schema.

    Two known drift modes seen in the wild:
    1. The model leaks its harmony scratchpad as a key, e.g.
       ``{"commentary to=assistant{": "classification", "new_filing_request": true, ...}``
       — strip any keys that look like scratchpad markers.
    2. The model flattens ``classification`` into a boolean key whose name is
       the actual classification value (``"new_filing_request": true``) instead
       of nesting it under ``"classification"``.

    Returns a copy of the dict with these issues normalized in place. If the
    model emitted a clean payload the dict is returned unchanged in shape.
    """
    out: dict[str, Any] = {}
    rescued_classification: str | None = None

    for key, value in parsed.items():
        # Drop scratchpad / harmony token leaks
        if (
            "commentary" in key
            or "to=assistant" in key
            or "<|" in key
            or key.endswith("{")
            or key.startswith("{")
        ):
            continue
        # Recover classification flattened as a boolean field
        if (
            key in _VALID_CLASSIFICATIONS
            and value is True
            and rescued_classification is None
        ):
            rescued_classification = key
            continue
        out[key] = value

    if "classification" not in out and rescued_classification is not None:
        out["classification"] = rescued_classification

    return out


@router.post(
    "/triage-message",
    response_model=TriageResponse,
    summary="Classify an inbound customer message (Together AI gpt-oss-20b)",
)
async def triage_message(
    body: TriageRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> TriageResponse:
    """Run a customer message through Together AI for structured triage.

    Returns intent + urgency + entity extraction. The capability that calls
    this is auto-audited, so every classification is queryable later.
    """
    _check_auth(x_braid_auth)

    if not settings.together_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TOGETHER_API_KEY not configured",
        )

    try:
        raw = await asyncio.to_thread(
            _call_together_sync,
            body.message_text,
            body.channel,
            body.sender,
            body.language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("braid triage: together call failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together api call failed: {exc}",
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("braid triage: invalid json from together: %r", raw)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together returned non-json: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "together returned a non-object json payload",
        )

    normalized = _normalize_triage_payload(parsed)
    normalized["model"] = _TRIAGE_MODEL

    try:
        return TriageResponse.model_validate(normalized)
    except ValidationError as exc:
        logger.warning(
            "braid triage: schema validation failed raw=%r normalized=%r errors=%s",
            parsed,
            normalized,
            exc.errors(),
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together output failed schema: {exc.errors()}",
        ) from exc

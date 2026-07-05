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
from app.cases.models import Case
from app.config import settings
from app.database import get_db
from app.documents.models import DocumentStatus
from app.required_documents.models import CaseRequiredDocument
from app.services.euipo.client import EUIPOClientError
from app.services.euipo.trademark_search import search_trademarks
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
        f"https://explorer.solana.com/address/{pda_str}{settings.solana_explorer_cluster_suffix}"
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
# Document completeness scoring (rule-based, jurisdiction-aware)
# ────────────────────────────────────────────────────────────────────


class ScoreDocumentCompletenessRequest(BaseModel):
    case_id: uuid.UUID = Field(..., description="Etornie case UUID")


class CompletenessBreakdown(BaseModel):
    required: int
    pending: int
    uploaded: int
    approved: int
    rejected: int
    cancelled: int


class MissingDocument(BaseModel):
    document_name: str
    status: str
    notes: str | None = None


class ScoreDocumentCompletenessResponse(BaseModel):
    case_id: uuid.UUID
    jurisdiction: str | None
    case_status: str | None
    breakdown: CompletenessBreakdown
    completeness_pct: float = Field(
        ..., ge=0.0, le=1.0, description="approved / required (0 if required=0)"
    )
    ready_to_file: bool
    missing_documents: list[MissingDocument]
    reasoning: str
    error: str | None = None


def _completeness_decline(
    case_id: uuid.UUID, error: str
) -> ScoreDocumentCompletenessResponse:
    return ScoreDocumentCompletenessResponse(
        case_id=case_id,
        jurisdiction=None,
        case_status=None,
        breakdown=CompletenessBreakdown(
            required=0,
            pending=0,
            uploaded=0,
            approved=0,
            rejected=0,
            cancelled=0,
        ),
        completeness_pct=0.0,
        ready_to_file=False,
        missing_documents=[],
        reasoning=error,
        error=error,
    )


@router.post(
    "/score-document-completeness",
    response_model=ScoreDocumentCompletenessResponse,
    summary="Score how ready a case's required-document checklist is for filing",
)
async def score_document_completeness(
    body: ScoreDocumentCompletenessRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
    db: AsyncSession = Depends(get_db),
) -> ScoreDocumentCompletenessResponse:
    """Aggregate the case_required_documents checklist into a structured
    completeness score so BRAID can decide whether a filing can proceed
    or what's still needed.

    Always returns ``HTTP 200`` with a structured outcome (including the
    "case not found" path) so BRAID can reason over auditable failures.
    """
    _check_auth(x_braid_auth)

    case = await db.get(Case, body.case_id)
    if case is None:
        return _completeness_decline(
            body.case_id, f"case {body.case_id} not found"
        )

    stmt = select(CaseRequiredDocument).where(
        CaseRequiredDocument.case_id == body.case_id
    )
    rows = (await db.execute(stmt)).scalars().all()

    counters = {s.value: 0 for s in DocumentStatus}
    missing: list[MissingDocument] = []
    for r in rows:
        counters[r.status.value] += 1
        if r.status != DocumentStatus.approved:
            missing.append(
                MissingDocument(
                    document_name=r.document_name,
                    status=r.status.value,
                    notes=r.notes,
                )
            )

    required = len(rows)
    approved = counters.get(DocumentStatus.approved.value, 0)
    completeness_pct = (approved / required) if required > 0 else 0.0
    ready_to_file = required > 0 and approved == required

    if required == 0:
        reasoning = (
            "No required-document checklist generated for this case yet. "
            "Run the required-documents generator before scoring."
        )
    elif ready_to_file:
        reasoning = (
            f"All {required} required documents are approved. "
            f"Case is ready for filing in {case.jurisdiction or 'the configured jurisdiction'}."
        )
    else:
        outstanding = required - approved
        reasoning = (
            f"{approved}/{required} required documents approved "
            f"({completeness_pct:.0%}). {outstanding} item(s) still need "
            f"attention: "
            + ", ".join(
                f"{m.document_name} [{m.status}]" for m in missing[:5]
            )
            + ("..." if len(missing) > 5 else "")
        )

    return ScoreDocumentCompletenessResponse(
        case_id=body.case_id,
        jurisdiction=case.jurisdiction,
        case_status=getattr(case.status, "value", str(case.status))
        if case.status is not None
        else None,
        breakdown=CompletenessBreakdown(
            required=required,
            pending=counters.get(DocumentStatus.pending.value, 0),
            uploaded=counters.get(DocumentStatus.uploaded.value, 0),
            approved=approved,
            rejected=counters.get(DocumentStatus.rejected.value, 0),
            cancelled=counters.get(DocumentStatus.cancelled.value, 0),
        ),
        completeness_pct=round(completeness_pct, 4),
        ready_to_file=ready_to_file,
        missing_documents=missing,
        reasoning=reasoning,
    )


# ────────────────────────────────────────────────────────────────────
# Trademark conflict check (EUIPO real search; others not yet integrated)
# ────────────────────────────────────────────────────────────────────


class TrademarkRiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TrademarkMatch(BaseModel):
    mark_text: str | None = None
    application_number: str | None = None
    status: str | None = None
    owner: str | None = None
    nice_classes: list[int] | None = None
    office: str | None = None
    is_exact_match: bool = False


class CheckTrademarkConflictRequest(BaseModel):
    mark_text: str = Field(..., min_length=1, max_length=256)
    jurisdiction: Literal["eu", "uk", "au", "wipo", "unknown"] = "eu"
    nice_classes: list[int] | None = Field(
        default=None,
        description="Optional Nice class numbers to narrow the search",
    )
    page_size: int = Field(
        default=20,
        ge=10,
        le=100,
        description="EUIPO requires page_size >= 10",
    )


class CheckTrademarkConflictResponse(BaseModel):
    jurisdiction: str
    mark_text: str
    nice_classes: list[int] | None
    searched: bool = Field(
        ..., description="True if a real search ran; false for stub offices"
    )
    integration_status: Literal[
        "live", "not_yet_integrated", "search_failed"
    ]
    match_count: int = 0
    top_matches: list[TrademarkMatch] = Field(default_factory=list)
    exact_match_found: bool = False
    risk_level: TrademarkRiskLevel = TrademarkRiskLevel.NONE
    reasoning: str
    error: str | None = None


def _stub_office(
    body: CheckTrademarkConflictRequest, office: str
) -> CheckTrademarkConflictResponse:
    return CheckTrademarkConflictResponse(
        jurisdiction=body.jurisdiction,
        mark_text=body.mark_text,
        nice_classes=body.nice_classes,
        searched=False,
        integration_status="not_yet_integrated",
        reasoning=(
            f"{office} trademark search is not yet integrated into Etornie. "
            f"To clear conflicts in {office}, an operator must run the "
            f"search manually via the office's public registry. Do NOT "
            f"recommend filing in {office} based on this BRAID call alone."
        ),
    )


def _classify_risk(
    match_count: int, exact_match: bool
) -> TrademarkRiskLevel:
    if exact_match:
        return TrademarkRiskLevel.HIGH
    if match_count == 0:
        return TrademarkRiskLevel.NONE
    if match_count <= 3:
        return TrademarkRiskLevel.LOW
    if match_count <= 10:
        return TrademarkRiskLevel.MEDIUM
    return TrademarkRiskLevel.HIGH


def _parse_euipo_results(
    raw: dict[str, Any], target_mark: str
) -> tuple[int, list[TrademarkMatch], bool]:
    """Best-effort extraction from the EUIPO search payload.

    EUIPO response shape varies by version; we look for common keys
    (``content`` / ``trademarks`` / ``items``) and pull a few stable
    fields per match. Anything we cannot find stays null in the output.
    """
    items: list[dict[str, Any]] = []
    for key in ("content", "trademarks", "items", "results"):
        v = raw.get(key)
        if isinstance(v, list):
            items = v
            break

    target_normalized = target_mark.strip().casefold()
    matches: list[TrademarkMatch] = []
    exact_found = False

    for item in items:
        if not isinstance(item, dict):
            continue
        # Try a handful of known field names
        mark_text = (
            item.get("wordMarkSpecification", {}).get("verbalElement")
            if isinstance(item.get("wordMarkSpecification"), dict)
            else None
        ) or item.get("verbalElement") or item.get("markName") or item.get("mark")
        appno = (
            item.get("applicationNumber")
            or item.get("registrationNumber")
            or item.get("id")
        )
        status = item.get("status") or item.get("markStatus")
        owner = (
            item.get("applicantName")
            or item.get("owner")
            or (
                item.get("applicants", [{}])[0].get("name")
                if isinstance(item.get("applicants"), list)
                and item.get("applicants")
                else None
            )
        )
        classes_raw = item.get("niceClasses") or item.get("classes")
        classes: list[int] | None = None
        if isinstance(classes_raw, list):
            classes = [
                int(c)
                for c in classes_raw
                if isinstance(c, (int, str)) and str(c).isdigit()
            ]

        is_exact = (
            isinstance(mark_text, str)
            and mark_text.strip().casefold() == target_normalized
        )
        if is_exact:
            exact_found = True

        matches.append(
            TrademarkMatch(
                mark_text=mark_text if isinstance(mark_text, str) else None,
                application_number=str(appno) if appno is not None else None,
                status=str(status) if status is not None else None,
                owner=str(owner) if owner is not None else None,
                nice_classes=classes,
                office=item.get("office") or item.get("officeCode"),
                is_exact_match=is_exact,
            )
        )

    total = (
        raw.get("totalElements")
        or raw.get("totalResults")
        or raw.get("total")
        or len(items)
    )
    try:
        total_int = int(total)
    except (TypeError, ValueError):
        total_int = len(items)

    return total_int, matches, exact_found


@router.post(
    "/check-trademark-conflict",
    response_model=CheckTrademarkConflictResponse,
    summary="Search for conflicting trademarks (EUIPO live; UK/AU/WIPO not yet integrated)",
)
async def check_trademark_conflict(
    body: CheckTrademarkConflictRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> CheckTrademarkConflictResponse:
    """Run a trademark conflict check.

    EU/EUIPO uses the existing live EUIPO trademark-search service. Other
    jurisdictions return ``integration_status: not_yet_integrated`` with a
    clear reasoning string so BRAID can route the user to a manual step
    without inventing search results.
    """
    _check_auth(x_braid_auth)

    j = body.jurisdiction.lower()
    if j == "uk":
        return _stub_office(body, "UKIPO")
    if j == "au":
        return _stub_office(body, "IP Australia")
    if j == "wipo":
        return _stub_office(body, "WIPO Madrid")
    if j == "unknown":
        return CheckTrademarkConflictResponse(
            jurisdiction=body.jurisdiction,
            mark_text=body.mark_text,
            nice_classes=body.nice_classes,
            searched=False,
            integration_status="not_yet_integrated",
            reasoning=(
                "Jurisdiction unknown — refusing to default. Specify "
                "one of: eu, uk, au, wipo."
            ),
        )

    # ── live EUIPO search ──
    try:
        raw = await search_trademarks(
            mark_text=body.mark_text,
            nice_classes=body.nice_classes,
            page=0,
            page_size=body.page_size,
        )
    except EUIPOClientError as exc:
        logger.warning("braid trademark conflict: EUIPO error: %s", exc)
        return CheckTrademarkConflictResponse(
            jurisdiction=body.jurisdiction,
            mark_text=body.mark_text,
            nice_classes=body.nice_classes,
            searched=False,
            integration_status="search_failed",
            reasoning=(
                "EUIPO search failed; cannot conclude on conflict risk. "
                "Investigate the API/credentials before recommending action."
            ),
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("braid trademark conflict: unexpected error")
        return CheckTrademarkConflictResponse(
            jurisdiction=body.jurisdiction,
            mark_text=body.mark_text,
            nice_classes=body.nice_classes,
            searched=False,
            integration_status="search_failed",
            reasoning="Unexpected backend error during EUIPO search.",
            error=str(exc),
        )

    match_count, all_matches, exact_found = _parse_euipo_results(
        raw, body.mark_text
    )
    top = all_matches[:5]
    risk = _classify_risk(match_count, exact_found)

    if exact_found:
        reasoning = (
            f"EXACT MATCH found in EUIPO for '{body.mark_text}'. "
            f"Filing risk is HIGH; do not proceed without attorney review "
            f"of the conflicting registration(s)."
        )
    elif match_count == 0:
        reasoning = (
            f"No EUIPO matches found for '{body.mark_text}'"
            + (
                f" in classes {body.nice_classes}."
                if body.nice_classes
                else "."
            )
            + " Conflict risk on EUIPO is currently low; still confirm "
            "with the attorney before filing."
        )
    else:
        reasoning = (
            f"{match_count} EUIPO matches found for '{body.mark_text}'"
            + (
                f" in classes {body.nice_classes}."
                if body.nice_classes
                else "."
            )
            + f" Risk level estimated {risk.value}; review the top "
            f"matches before filing."
        )

    return CheckTrademarkConflictResponse(
        jurisdiction=body.jurisdiction,
        mark_text=body.mark_text,
        nice_classes=body.nice_classes,
        searched=True,
        integration_status="live",
        match_count=match_count,
        top_matches=top,
        exact_match_found=exact_found,
        risk_level=risk,
        reasoning=reasoning,
    )


# ────────────────────────────────────────────────────────────────────
# Nice classification validation (Together AI gpt-oss-20b)
# ────────────────────────────────────────────────────────────────────


_NICE_SYSTEM_PROMPT = """You are an experienced trademark paralegal validating \
a Nice Classification (11th edition, 45 classes) selection for a trademark filing.

Your only job: read the mark description + the user's proposed Nice classes, \
then produce a structured assessment of fit, plus suggested missing and surplus \
classes.

Reference (memorize these high-level groups, do NOT cite specifics you are \
unsure about):
- Goods classes 1-34 (chemicals, paints, cosmetics, fuels, pharma, metals, \
machines, tools, scientific & software 9, medical instruments 10, vehicles \
12, jewelry 14, paper 16, leather 18, furniture 20, household 21, textiles \
24, clothing 25, games/toys 28, food 29-31, beverages 32-33, tobacco 34)
- Service classes 35-45 (advertising/business 35, finance/insurance 36, \
construction 37, telecommunications 38, transport 39, materials treatment \
40, education/entertainment 41, scientific & technological services 42 \
[includes SaaS / hosted software], food/lodging 43, medical/veterinary 44, \
legal/security/personal 45)

Output rules (non-negotiable):
1. Output a SINGLE JSON object. Nothing before, nothing after. No markdown, \
no scratchpad, no "commentary to=assistant" wrappers.
2. The object MUST start with the literal key "classes_consistent" (boolean).
3. confidence: honest 0..1 estimate.
4. class_assessments: array, ONE entry per class in proposed_classes, in the \
same order. Each entry: {class_no:int, justification:string, fit:"good"|"weak"|"wrong"}.
5. missing_recommended_classes: array of integer class numbers NOT in \
proposed_classes that should be considered (e.g. SaaS mark missing class 42, \
clothing brand missing class 25). Only suggest classes you are confident apply.
6. surplus_unwarranted_classes: array of integer class numbers in \
proposed_classes that do NOT plausibly match the mark description.
7. recommended_action: one short sentence ("proceed with current selection", \
"add class 42 for SaaS coverage before filing", "remove class 25; mark does \
not cover apparel", "review with attorney — significant goods/services overlap").
8. escalation_required: true if confidence < 0.6, OR if class_assessments \
contain any "wrong", OR surplus_unwarranted_classes is non-empty (suggests \
overreach), OR mark description is too vague to classify.
9. reasoning: one or two sentences citing the description, written for an \
attorney audit reader.
10. Never invent classes outside 1..45. If unsure about a class, do NOT \
include it in missing_recommended_classes.

Concrete example.
INPUT:
  mark_description: "A mobile app and web platform for booking certified \
private chefs to cook in-home meals; subscription-based"
  proposed_classes: [9, 43]
EXPECTED OUTPUT:
{"classes_consistent":true,"confidence":0.9,"class_assessments":[\
{"class_no":9,"justification":"Mobile and web application software","fit":"good"},\
{"class_no":43,"justification":"Providing food and drink (in-home chef booking)","fit":"good"}],\
"missing_recommended_classes":[35,42],\
"surplus_unwarranted_classes":[],\
"recommended_action":"add class 42 (SaaS hosting) and class 35 (online booking platform) before filing",\
"escalation_required":false,\
"reasoning":"Mark covers both software (cl. 9) and chef-booking services (cl. 43); a SaaS-style platform also typically requires class 42 for the hosted software service and class 35 for the online booking marketplace function."}"""


_NICE_JSON_HINT = """{
  "classes_consistent": true,
  "confidence": 0.0,
  "class_assessments": [
    {"class_no": 0, "justification": "<short>", "fit": "<good|weak|wrong>"}
  ],
  "missing_recommended_classes": [],
  "surplus_unwarranted_classes": [],
  "recommended_action": "<short sentence>",
  "escalation_required": false,
  "reasoning": "<one or two sentences>"
}"""


class NiceFit(str, Enum):
    GOOD = "good"
    WEAK = "weak"
    WRONG = "wrong"


class ClassAssessment(BaseModel):
    class_no: int = Field(..., ge=1, le=45)
    justification: str = Field(..., min_length=1, max_length=512)
    fit: NiceFit


class ValidateNiceClassificationRequest(BaseModel):
    mark_description: str = Field(..., min_length=3, max_length=4000)
    proposed_classes: list[int] = Field(
        ..., min_length=1, max_length=45
    )
    mark_name: str | None = Field(default=None, max_length=256)
    language: str | None = Field(default=None, max_length=16)


class ValidateNiceClassificationResponse(BaseModel):
    classes_consistent: bool
    confidence: float = Field(ge=0.0, le=1.0)
    class_assessments: list[ClassAssessment]
    missing_recommended_classes: list[int] = Field(default_factory=list)
    surplus_unwarranted_classes: list[int] = Field(default_factory=list)
    recommended_action: str = Field(..., min_length=1, max_length=512)
    escalation_required: bool
    reasoning: str = Field(..., min_length=1, max_length=2000)
    proposed_classes: list[int]
    model: str


def _validate_proposed_classes(classes: list[int]) -> list[int]:
    """Reject Nice numbers outside 1..45 and dedupe while preserving order."""
    seen: set[int] = set()
    out: list[int] = []
    for c in classes:
        if 1 <= c <= 45 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _call_together_nice_sync(
    mark_description: str,
    proposed_classes: list[int],
    mark_name: str | None,
    language: str | None,
) -> str:
    client = Together(api_key=settings.together_api_key)
    user_payload_lines = [
        f"mark_name: {mark_name or '(unspecified)'}",
        f"language_hint: {language or 'auto'}",
        f"proposed_classes: {proposed_classes}",
        "",
        "MARK DESCRIPTION:",
        mark_description,
        "",
        "Respond with JSON exactly matching this shape (fill in real values):",
        _NICE_JSON_HINT,
    ]
    response = client.chat.completions.create(
        model=_TRIAGE_MODEL,
        messages=[
            {"role": "system", "content": _NICE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_payload_lines)},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1500,
    )
    return response.choices[0].message.content or ""


def _normalize_nice_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    """Strip gpt-oss-20b harmony scratchpad leaks, same defense as triage/office."""
    out: dict[str, Any] = {}
    for key, value in parsed.items():
        if (
            "commentary" in key
            or "to=assistant" in key
            or "<|" in key
            or key.endswith("{")
            or key.startswith("{")
        ):
            continue
        out[key] = value
    return out


@router.post(
    "/validate-nice-classification",
    response_model=ValidateNiceClassificationResponse,
    summary="Validate Nice class selection vs mark description (Together AI)",
)
async def validate_nice_classification(
    body: ValidateNiceClassificationRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> ValidateNiceClassificationResponse:
    """Run a mark description + proposed Nice classes through Together AI for
    structured classification validation. The capability that calls this is
    auto-audited so every classification check is queryable later."""
    _check_auth(x_braid_auth)

    if not settings.together_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TOGETHER_API_KEY not configured",
        )

    proposed = _validate_proposed_classes(body.proposed_classes)
    if not proposed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "proposed_classes must contain at least one valid class in 1..45",
        )

    try:
        raw = await asyncio.to_thread(
            _call_together_nice_sync,
            body.mark_description,
            proposed,
            body.mark_name,
            body.language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("braid validate_nice: together call failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together api call failed: {exc}",
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("braid validate_nice: invalid json from together: %r", raw)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together returned non-json: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "together returned a non-object json payload",
        )

    normalized = _normalize_nice_payload(parsed)
    normalized["proposed_classes"] = proposed
    normalized["model"] = _TRIAGE_MODEL

    try:
        return ValidateNiceClassificationResponse.model_validate(normalized)
    except ValidationError as exc:
        logger.warning(
            "braid validate_nice: schema validation failed raw=%r normalized=%r errors=%s",
            parsed,
            normalized,
            exc.errors(),
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together output failed schema: {exc.errors()}",
        ) from exc


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


# ────────────────────────────────────────────────────────────────────
# IP office response routing (Together AI gpt-oss-20b)
# ────────────────────────────────────────────────────────────────────


_OFFICE_SYSTEM_PROMPT = """You are a senior IP paralegal classifying ONE \
inbound communication from an IP office (UKIPO, EUIPO, IP Australia, WIPO).

Your only job: read the office text and produce a structured classification \
+ urgency + entity extraction + deadline so a docketing system can route it \
correctly.

Classification taxonomy (pick exactly one):
- acceptance              : application accepted; will proceed to publication / registration
- provisional_refusal     : examiner raised an objection; substantive response required (e.g. Article 8(1)(b) similarity, descriptive mark, bad faith)
- office_action_request   : examiner asks for clarification, correction, or additional documents (non-substantive)
- opposition_notice       : third party has filed opposition during the publication window
- examination_report      : initial examination findings, may bundle minor objections
- registration_certificate: final registration, certificate or registration number issued
- fee_request             : additional fees required (extra classes, late filing, renewal)
- status_update           : informational only, no action required from applicant
- withdrawal_acknowledgment: office acknowledges applicant withdrawal / abandonment
- unknown                 : cannot determine from the text

Urgency levels (driven by deadline + legal weight):
- low      : informational, no deadline, or deadline > 60 days
- medium   : deadline 14-60 days, routine response
- high     : deadline 4-14 days, OR substantive objection requiring attorney drafting
- critical : deadline ≤ 3 days (or already passed), OR opposition / refusal that risks loss of rights

Entity extraction (set null if not present):
- application_number  : official filing number (e.g. UK00012345, EUTM018xxxxxxx, AU2345678)
- mark_name           : the trademark / mark text
- opposition_basis    : article / section cited (e.g. "Article 8(1)(b)", "Section 5(2)(b)")
- nice_classes        : list of Nice classification numbers as integers, e.g. [9, 35, 42]
- opponent            : name of the opposing party if an opposition
- deadline_iso        : ISO date YYYY-MM-DD if a clear deadline is mentioned

Output rules (non-negotiable):
1. Output a SINGLE JSON object. Nothing before, nothing after. No markdown, \
no scratchpad, no "commentary to=assistant" wrappers.
2. The object MUST start with the literal key "classification" whose value is \
the classification string (NOT a boolean). Do not flatten classification into \
a separate boolean key.
3. confidence: honest 0..1 estimate.
4. recommended_action: one short sentence (e.g. "draft Article 8(1)(b) \
response by deadline", "forward fee notice to client for payment", "notify \
client of registration certificate").
5. requires_attorney_review: true for any provisional_refusal, opposition_notice, \
or anything ambiguous involving legal arguments. Routine fee/status items can \
be false.
6. escalation_required: true if confidence < 0.6, urgency is critical, or \
the response could result in loss of rights (refusal, opposition, missed \
deadline).
7. reasoning: one or two sentences explaining the classification, citing the \
text — this is written into the audit trail and read by attorneys later.
8. Never invent entity values. If unsure, leave them null.

Concrete example.
INPUT: "We refer to UK trade mark application no. UK00003456789 for the mark \
'FOOBAR'. Following examination under Section 3(1)(b), the registrar finds the \
mark devoid of distinctive character. You have until 14 March 2026 to file \
written observations or amend the specification."
EXPECTED OUTPUT:
{"classification":"provisional_refusal","confidence":0.96,"urgency":"high",\
"recommended_action":"draft Section 3(1)(b) distinctiveness response by 2026-03-14",\
"extracted_entities":{"application_number":"UK00003456789","mark_name":"FOOBAR",\
"opposition_basis":"Section 3(1)(b)","nice_classes":null,"opponent":null,\
"deadline_iso":"2026-03-14"},"requires_attorney_review":true,\
"reasoning":"UKIPO has issued a substantive Section 3(1)(b) refusal on \
distinctiveness grounds with a 14 March 2026 response deadline.",\
"escalation_required":true}"""


_OFFICE_JSON_HINT = """{
  "classification": "<one of: acceptance | provisional_refusal | office_action_request | opposition_notice | examination_report | registration_certificate | fee_request | status_update | withdrawal_acknowledgment | unknown>",
  "confidence": 0.0,
  "urgency": "<low | medium | high | critical>",
  "recommended_action": "<short sentence>",
  "extracted_entities": {
    "application_number": null,
    "mark_name": null,
    "opposition_basis": null,
    "nice_classes": null,
    "opponent": null,
    "deadline_iso": null
  },
  "requires_attorney_review": false,
  "reasoning": "<one or two sentences>",
  "escalation_required": false
}"""


class OfficeClassification(str, Enum):
    ACCEPTANCE = "acceptance"
    PROVISIONAL_REFUSAL = "provisional_refusal"
    OFFICE_ACTION_REQUEST = "office_action_request"
    OPPOSITION_NOTICE = "opposition_notice"
    EXAMINATION_REPORT = "examination_report"
    REGISTRATION_CERTIFICATE = "registration_certificate"
    FEE_REQUEST = "fee_request"
    STATUS_UPDATE = "status_update"
    WITHDRAWAL_ACKNOWLEDGMENT = "withdrawal_acknowledgment"
    UNKNOWN = "unknown"


class OfficeEntities(BaseModel):
    application_number: str | None = Field(default=None, max_length=64)
    mark_name: str | None = Field(default=None, max_length=256)
    opposition_basis: str | None = Field(default=None, max_length=128)
    nice_classes: list[int] | None = None
    opponent: str | None = Field(default=None, max_length=256)
    deadline_iso: str | None = Field(default=None, max_length=32)


class RouteOfficeResponseRequest(BaseModel):
    response_text: str = Field(..., min_length=1, max_length=12000)
    office: Literal["ukipo", "euipo", "ipau", "wipo", "unknown"] = "unknown"
    case_id: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=16)


class RouteOfficeResponseResult(BaseModel):
    classification: OfficeClassification
    confidence: float = Field(ge=0.0, le=1.0)
    urgency: TriageUrgency
    recommended_action: str = Field(..., min_length=1, max_length=512)
    extracted_entities: OfficeEntities = Field(default_factory=OfficeEntities)
    requires_attorney_review: bool
    reasoning: str = Field(..., min_length=1, max_length=2000)
    escalation_required: bool
    model: str


def _call_together_office_sync(
    response_text: str,
    office: str,
    case_id: str | None,
    language: str | None,
) -> str:
    client = Together(api_key=settings.together_api_key)

    user_payload_lines = [
        f"office: {office}",
        f"case_id: {case_id or 'unknown'}",
        f"language_hint: {language or 'auto'}",
        "",
        "OFFICE TEXT:",
        response_text,
        "",
        "Respond with JSON exactly matching this shape (fill in real values):",
        _OFFICE_JSON_HINT,
    ]

    response = client.chat.completions.create(
        model=_TRIAGE_MODEL,
        messages=[
            {"role": "system", "content": _OFFICE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_payload_lines)},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


_VALID_OFFICE_CLASSIFICATIONS = {c.value for c in OfficeClassification}


def _normalize_office_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    """Same defensive normalization as triage; gpt-oss-20b sometimes leaks
    its harmony scratchpad or flattens the classification into a boolean
    key. Strip those and recover where possible."""
    out: dict[str, Any] = {}
    rescued_classification: str | None = None

    for key, value in parsed.items():
        if (
            "commentary" in key
            or "to=assistant" in key
            or "<|" in key
            or key.endswith("{")
            or key.startswith("{")
        ):
            continue
        if (
            key in _VALID_OFFICE_CLASSIFICATIONS
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
    "/route-office-response",
    response_model=RouteOfficeResponseResult,
    summary="Classify an IP office response (UKIPO/EUIPO/IPAU/WIPO) via Together AI",
)
async def route_office_response(
    body: RouteOfficeResponseRequest,
    x_braid_auth: str | None = Header(default=None, alias="X-Braid-Auth"),
) -> RouteOfficeResponseResult:
    """Run an IP office communication through Together AI for structured
    classification + entity extraction + deadline detection. The capability
    that calls this is auto-audited so every routing decision is queryable
    later."""
    _check_auth(x_braid_auth)

    if not settings.together_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TOGETHER_API_KEY not configured",
        )

    try:
        raw = await asyncio.to_thread(
            _call_together_office_sync,
            body.response_text,
            body.office,
            body.case_id,
            body.language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("braid route_office_response: together call failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together api call failed: {exc}",
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("braid route_office: invalid json from together: %r", raw)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together returned non-json: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "together returned a non-object json payload",
        )

    normalized = _normalize_office_payload(parsed)
    normalized["model"] = _TRIAGE_MODEL

    try:
        return RouteOfficeResponseResult.model_validate(normalized)
    except ValidationError as exc:
        logger.warning(
            "braid route_office: schema validation failed raw=%r normalized=%r errors=%s",
            parsed,
            normalized,
            exc.errors(),
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"together output failed schema: {exc.errors()}",
        ) from exc

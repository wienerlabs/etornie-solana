"""EUIPO API endpoints for Etornie platform.

Integrates EUIPO services with Etornie's case and document models.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.cases.service import get_case
from app.database import get_db
from app.services.euipo.client import EUIPOClientError
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/euipo", tags=["euipo"])


# ── OAuth Flow Endpoints ──


@router.get("/auth/authorize")
async def euipo_authorize(
    redirect_uri: str,
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> dict[str, str]:
    """Get EUIPO authorization URL for user login.

    Required before using filing/document/portfolio APIs.
    """
    from app.services.euipo.auth import get_authorize_url

    scopes = [
        "eutm-filing.application.read",
        "eutm-filing.application.write",
        "design-filing.application.read",
        "design-filing.application.write",
        "document-repository.documents.read",
        "document-repository.documents.write",
        "me.portfolio.read",
        "me.applicants.read",
        "me.account.read",
    ]
    url = get_authorize_url(redirect_uri, scopes)
    return {"authorize_url": url}


@router.post("/auth/callback")
async def euipo_callback(
    code: str,
    redirect_uri: str,
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> dict[str, str]:
    """Exchange EUIPO authorization code for access token."""
    from app.services.euipo.auth import exchange_authorization_code

    try:
        data = await exchange_authorization_code(code, redirect_uri)
        return {"status": "authenticated", "expires_in": str(data.get("expires_in", 28800))}
    except Exception as exc:
        raise HTTPException(502, f"EUIPO auth callback failed: {exc}") from exc


# ── Schemas ──


class TrademarkSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    nice_classes: list[int] | None = None
    offices: list[str] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class GoodsServicesSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    nice_class: int | None = Field(default=None, ge=1, le=45)
    language: str = "en"


class GoodsServicesValidateRequest(BaseModel):
    terms: list[dict[str, Any]]
    language: str = "en"


class DesignSearchRequest(BaseModel):
    query: str | None = None
    locarno_classes: list[str] | None = None
    holder: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class EUTMFilingRequest(BaseModel):
    case_id: uuid.UUID
    mark_text: str = Field(min_length=1, max_length=500)
    mark_type: str = "WORD"
    applicant_name: str
    applicant_address: str
    applicant_country: str
    language_first: str = "en"
    language_second: str = "fr"


class PortfolioRequest(BaseModel):
    ip_type: str | None = None
    status: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# ── Helper ──


def _handle_euipo_error(exc: EUIPOClientError) -> HTTPException:
    if exc.status_code == 401:
        return HTTPException(502, "EUIPO authentication failed")
    if exc.status_code == 429:
        return HTTPException(429, "EUIPO rate limit exceeded, try again later")
    return HTTPException(502, f"EUIPO API error: {exc.detail}")


# ── Trademark Search ──


@router.post("/trademark-search")
async def search_trademarks_endpoint(
    data: TrademarkSearchRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Search EUIPO trademark database."""
    from app.services.euipo.trademark_search import search_trademarks

    try:
        return await search_trademarks(
            mark_text=data.query,
            nice_classes=data.nice_classes,
            page=data.page - 1,  # EUIPO uses 0-based pages
            page_size=data.page_size,
        )
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


@router.get("/trademark-search/{trademark_id}")
async def get_trademark_endpoint(
    trademark_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get details of a specific trademark."""
    from app.services.euipo.trademark_search import get_trademark_details

    try:
        return await get_trademark_details(trademark_id)
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


# ── Goods & Services ──


@router.post("/goods-services/search")
async def search_goods_services_endpoint(
    data: GoodsServicesSearchRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Search EUIPO goods/services taxonomy."""
    from app.services.euipo.goods_services import search_terms

    try:
        return await search_terms(
            query=data.query,
            nice_class=data.nice_class,
            language=data.language,
        )
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


@router.post("/goods-services/validate")
async def validate_goods_services_endpoint(
    data: GoodsServicesValidateRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Validate goods/services classification against EUIPO standards."""
    from app.services.euipo.goods_services import validate_classification

    try:
        return await validate_classification(
            data.terms, source_language=data.language
        )
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


# ── EUTM Filing ──


@router.post("/eutm/file")
async def file_eutm_endpoint(
    data: EUTMFilingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> dict[str, Any]:
    """File an EUTM application from a case.

    Creates a draft application at EUIPO using case data.
    Admin or lawyer only.
    """
    from app.services.euipo.eutm_filing import create_application

    case = await get_case(db, data.case_id)
    if case is None:
        raise HTTPException(404, "Case not found")

    # Build Nice classes from case data
    nice_class_list = []
    if case.nice_classes:
        for cls_num in case.nice_classes.split(","):
            cls_num = cls_num.strip()
            if cls_num.isdigit():
                nice_class_list.append({
                    "classNumber": int(cls_num),
                    "language": data.language_first,
                    "terms": [],
                })

    try:
        result = await create_application(
            mark_text=data.mark_text,
            mark_feature=data.mark_type,
            nice_classes=nice_class_list,
            applicant={
                "name": data.applicant_name,
                "address": data.applicant_address,
                "country": data.applicant_country,
            },
            first_language=data.language_first,
            second_language=data.language_second,
        )
        logger.info(
            "EUTM application created for case %s: %s",
            case.case_number,
            result.get("applicationId", "unknown"),
        )
        return result
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=428,
            detail="EUIPO authorization required. Complete the OAuth flow first via /euipo/auth/authorize.",
        ) from exc


@router.get("/eutm/{application_id}")
async def get_eutm_application_endpoint(
    application_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get status of an EUTM application."""
    from app.services.euipo.eutm_filing import get_application

    try:
        return await get_application(application_id)
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


@router.post("/eutm/{application_id}/submit")
async def submit_eutm_endpoint(
    application_id: str,
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> dict[str, Any]:
    """Submit a draft EUTM application. Admin or lawyer only."""
    from app.services.euipo.eutm_filing import submit_application

    try:
        return await submit_application(application_id)
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


# ── Document Repository ──


@router.post("/documents/{application_id}/upload")
async def upload_euipo_document_endpoint(
    application_id: str,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> dict[str, Any]:
    """Upload an Etornie document to an EUIPO application.

    Reads the document from Etornie's storage and uploads it to EUIPO.
    """
    import os

    from app.config import settings
    from app.documents.service import get_document
    from app.services.euipo.document_repo import upload_document

    doc = await get_document(db, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")

    file_path = os.path.join(settings.upload_dir, doc.filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "Document file not found on disk")

    with open(file_path, "rb") as f:
        file_content = f.read()

    try:
        return await upload_document(
            application_id=application_id,
            file_content=file_content,
            filename=doc.filename,
            document_type=doc.document_type or "OTHER",
            content_type=doc.file_type or "application/pdf",
        )
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


# ── Portfolio (Me) ──


@router.post("/portfolio")
async def get_portfolio_endpoint(
    data: PortfolioRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get EUIPO IP portfolio."""
    from app.services.euipo.portfolio import get_portfolio

    try:
        return await get_portfolio(
            ip_type=data.ip_type,
            status=data.status,
            page=data.page,
            page_size=data.page_size,
        )
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc


# ── Design Search ──


@router.post("/design-search")
async def search_designs_endpoint(
    data: DesignSearchRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Search EUIPO design database."""
    from app.services.euipo.design_search import search_designs

    try:
        # Build RSQL from user input
        rsql_parts = []
        if data.query:
            escaped = data.query.strip().replace("'", "\\'")
            rsql_parts.append(f"applicants.name==*{escaped}*")
        if data.holder:
            escaped_h = data.holder.strip().replace("'", "\\'")
            rsql_parts.append(f"applicants.name==*{escaped_h}*")
        if data.locarno_classes:
            cls_str = ",".join(data.locarno_classes)
            rsql_parts.append(f"locarnoClasses=all=({cls_str})")
        rsql_query = " and ".join(rsql_parts) if rsql_parts else None

        return await search_designs(
            query=rsql_query,
            page=max(data.page - 1, 0),
            page_size=max(data.page_size, 10),
        )
    except EUIPOClientError as exc:
        raise _handle_euipo_error(exc) from exc

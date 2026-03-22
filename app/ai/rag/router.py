"""Router for AI / RAG endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import TogetherAIClient, get_ai_client
from app.ai.rag.schemas import (
    ChatRequest,
    ChatResponse,
    IndexResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.ai.rag.service import augmented_chat, index_document, search_similar
from app.auth.dependencies import get_current_user, require_role
from app.cases.service import get_case
from app.database import get_db
from app.documents.models import Document
from app.users.models import User, UserRole

router = APIRouter(prefix="/ai", tags=["ai"])


def _can_access_case(user: User, case: object) -> bool:
    """Check whether a user may view/interact with a case."""
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "assigned_lawyer_id", None):
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


@router.post("/index/{document_id}", response_model=IndexResponse)
async def index_document_endpoint(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
    ai_client: TogetherAIClient = Depends(get_ai_client),
) -> IndexResponse:
    """Index a document for RAG search. Admin or lawyer only."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Verify user can access the case this document belongs to
    case = await get_case(db, document.case_id)
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this document's case",
        )

    chunks_created = await index_document(db, ai_client, document_id)
    return IndexResponse(chunks_created=chunks_created)


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    ai_client: TogetherAIClient = Depends(get_ai_client),
) -> SearchResponse:
    """Search for similar content across documents.

    RBAC: only return results from cases the user can access.
    """
    # If a case_id is provided, verify access
    if body.case_id is not None:
        case = await get_case(db, body.case_id)
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found",
            )
        if not _can_access_case(current_user, case):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this case",
            )

    raw_results = await search_similar(
        db, ai_client, body.query, case_id=body.case_id, top_k=body.top_k
    )

    # Filter by case access for non-admin users when no specific case_id
    if body.case_id is None and current_user.role != UserRole.admin:
        filtered: list[dict] = []
        for r in raw_results:
            doc_result = await db.execute(
                select(Document).where(Document.id == r["document_id"])
            )
            doc = doc_result.scalar_one_or_none()
            if doc is None:
                continue
            case = await get_case(db, doc.case_id)
            if case is not None and _can_access_case(current_user, case):
                filtered.append(r)
        raw_results = filtered

    results = [SearchResult(**r) for r in raw_results]
    return SearchResponse(results=results)


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    ai_client: TogetherAIClient = Depends(get_ai_client),
) -> ChatResponse:
    """RAG-augmented chat. Only uses context from cases the user can access."""
    # If a case_id is provided, verify access
    if body.case_id is not None:
        case = await get_case(db, body.case_id)
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found",
            )
        if not _can_access_case(current_user, case):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this case",
            )

    result = await augmented_chat(
        db, ai_client, body.question, case_id=body.case_id
    )

    # Filter sources by case access for non-admin users
    sources = result["sources"]
    if body.case_id is None and current_user.role != UserRole.admin:
        filtered_sources: list[dict] = []
        for s in sources:
            doc_result = await db.execute(
                select(Document).where(Document.id == s["document_id"])
            )
            doc = doc_result.scalar_one_or_none()
            if doc is None:
                continue
            case = await get_case(db, doc.case_id)
            if case is not None and _can_access_case(current_user, case):
                filtered_sources.append(s)
        sources = filtered_sources

    return ChatResponse(
        answer=result["answer"],
        sources=[SearchResult(**s) for s in sources],
    )

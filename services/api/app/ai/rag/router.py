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
from app.ai.rag.service import index_document, search_similar
from app.auth.dependencies import get_current_user, require_role
from app.cases.service import get_case
from app.database import get_db
from app.documents.models import Document
from app.users.models import User, UserRole

IP_SYSTEM_PROMPT = """You are a Case Assistant for Etornie, an IP services platform. You answer questions about specific cases using document context provided to you.

CRITICAL RULES:
- You MUST use the information from the Document Context below to answer the question.
- If the context contains relevant data (country names, deadlines, required documents, fees, procedures), you MUST include it in your answer. NEVER say "not specified" or "not mentioned" when the information IS present in the context.
- Extract and present specific details: numbers, dates, country names, document names, procedures.
- If the context is in Turkish, you can still answer in the user's language by translating the relevant data.
- Only say information is unavailable if you have genuinely searched the entire context and it is truly not there.
- Be concise, structured, and professional.
- Respond in the same language as the user's question."""

router = APIRouter(prefix="/ai", tags=["ai"])


def _can_access_case(user: User, case: object) -> bool:
    """Check whether a user may view/interact with a case."""
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


@router.post("/index/{document_id}", response_model=IndexResponse)
async def index_document_endpoint(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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


@router.post("/rag/chat", response_model=ChatResponse)
async def rag_chat_endpoint(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    ai_client: TogetherAIClient = Depends(get_ai_client),
) -> ChatResponse:
    """RAG-augmented case assistant. Requires case_id.

    Searches relevant document chunks for the case, injects them as context,
    and generates an answer using Together AI.
    """
    if body.case_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="case_id is required for Case Assistant",
        )

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

    # Search for relevant document chunks
    sources: list[dict] = []
    context_text = ""
    try:
        similar_chunks = await search_similar(
            db, ai_client, body.question, case_id=body.case_id, top_k=5
        )
        if similar_chunks:
            context_text = "\n\n---\n\n".join(
                chunk["content"] for chunk in similar_chunks
            )
            sources = [
                {
                    "content": chunk["content"],
                    "score": chunk["score"],
                    "document_id": chunk["document_id"],
                }
                for chunk in similar_chunks
            ]
    except HTTPException:
        pass  # Embedding service unavailable — answer without context

    # Build prompt with document context
    system = IP_SYSTEM_PROMPT
    if context_text:
        system += f"\n\nDocument Context:\n{context_text}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": body.question},
    ]

    try:
        answer = await ai_client.chat(messages=messages, temperature=0.3)
    finally:
        await ai_client.close()

    return ChatResponse(
        answer=answer,
        sources=[SearchResult(**s) for s in sources],
    )

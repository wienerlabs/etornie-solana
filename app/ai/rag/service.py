"""RAG pipeline: text extraction, chunking, indexing, search, and augmented chat."""

import json
import logging
import math
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import TogetherAIClient
from app.ai.rag.models import DocumentChunk
from app.documents.models import Document

logger = logging.getLogger(__name__)


def _read_text_file(file_path: str) -> str:
    """Synchronous helper to read a text file."""
    return Path(file_path).read_text(encoding="utf-8")


def _read_pdf_bytes(file_path: str) -> str:
    """Synchronous helper to read a PDF file with basic text extraction."""
    raw = Path(file_path).read_bytes()
    return raw.decode("utf-8", errors="ignore")


async def extract_text_from_file(file_path: str) -> str:
    """Extract text content from a document file.

    Supports .txt, .md files directly.
    For .pdf: reads raw bytes and attempts to decode (basic approach).
    Unsupported formats return an empty string.
    """
    lower_path = file_path.lower()

    if lower_path.endswith((".txt", ".md")):
        try:
            return _read_text_file(file_path)
        except Exception:
            logger.warning("Failed to read text file: %s", file_path)
            return ""

    if lower_path.endswith(".pdf"):
        try:
            return _read_pdf_bytes(file_path)
        except Exception:
            logger.warning("Failed to extract text from PDF: %s", file_path)
            return ""

    logger.warning("Unsupported file type for text extraction: %s", file_path)
    return ""


async def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[str]:
    """Split text into overlapping chunks for embedding.

    Args:
        text: The full text to split.
        chunk_size: Maximum number of characters per chunk.
        overlap: Number of overlapping characters between consecutive chunks.

    Returns:
        A list of text chunks.
    """
    if not text or not text.strip():
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= text_len:
            break
        start += chunk_size - overlap

    return chunks


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def index_document(
    db: AsyncSession,
    ai_client: TogetherAIClient,
    document_id: uuid.UUID,
) -> int:
    """Index a document for RAG search.

    1. Get document from DB
    2. Extract text from file
    3. Chunk the text
    4. Get embeddings for each chunk via ai_client.embed()
    5. Store in document_chunks table

    Returns:
        Number of chunks created.
    """
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        return 0

    text = await extract_text_from_file(document.file_path)
    if not text.strip():
        return 0

    chunks = await chunk_text(text)
    if not chunks:
        return 0

    embeddings = await ai_client.embed(chunks)

    for idx, (chunk_text_content, embedding) in enumerate(zip(chunks, embeddings)):
        chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=idx,
            content=chunk_text_content,
            embedding=json.dumps(embedding),
        )
        db.add(chunk)

    await db.flush()
    return len(chunks)


async def search_similar(
    db: AsyncSession,
    ai_client: TogetherAIClient,
    query: str,
    case_id: uuid.UUID | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Search for similar document chunks.

    1. Embed the query
    2. Load document_chunks (optionally filtered by case_id via document)
    3. Compute cosine similarity in Python
    4. Return top_k results sorted by score descending.

    Returns:
        List of dicts with keys: content, score, document_id.
    """
    query_embeddings = await ai_client.embed([query])
    query_vec = query_embeddings[0]

    stmt = select(DocumentChunk)
    if case_id is not None:
        stmt = stmt.join(Document, DocumentChunk.document_id == Document.id).where(
            Document.case_id == case_id
        )

    result = await db.execute(stmt)
    all_chunks = list(result.scalars().all())

    scored: list[dict] = []
    for chunk in all_chunks:
        if chunk.embedding is None:
            continue
        chunk_vec = json.loads(chunk.embedding)
        score = _cosine_similarity(query_vec, chunk_vec)
        scored.append(
            {
                "content": chunk.content,
                "score": round(score, 4),
                "document_id": chunk.document_id,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


async def augmented_chat(
    db: AsyncSession,
    ai_client: TogetherAIClient,
    question: str,
    case_id: uuid.UUID | None = None,
) -> dict:
    """RAG-augmented chat: search relevant docs, then answer with context.

    1. Search similar chunks
    2. Build system prompt with context
    3. Call ai_client.chat()
    4. Return { answer, sources }
    """
    similar_chunks = await search_similar(
        db, ai_client, question, case_id=case_id, top_k=5
    )

    context_parts = [chunk["content"] for chunk in similar_chunks]
    context_text = "\n\n---\n\n".join(context_parts) if context_parts else ""

    system_prompt = (
        "You are a helpful legal assistant for Etornie, an IP and patent services firm. "
        "Answer the user's question using the provided document context. "
        "If the context does not contain relevant information, say so clearly.\n\n"
        f"Document Context:\n{context_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    answer = await ai_client.chat(messages)

    sources = [
        {
            "content": chunk["content"],
            "score": chunk["score"],
            "document_id": chunk["document_id"],
        }
        for chunk in similar_chunks
    ]

    return {"answer": answer, "sources": sources}

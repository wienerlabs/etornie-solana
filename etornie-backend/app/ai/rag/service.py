"""RAG pipeline: text extraction, chunking, indexing, search, and augmented chat."""

import json
import logging
import math
import re
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


def _read_pdf_pages(file_path: str) -> list[str]:
    """Read a PDF and return a list of per-page text strings."""
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    pages: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").replace("\x00", "")
        if text.strip():
            pages.append(text)
    return pages


async def extract_text_from_file(file_path: str) -> str:
    """Extract text content from a document file.

    Supports .txt, .md files directly.
    For .pdf: extracts text per page and joins them.
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
            pages = _read_pdf_pages(file_path)
            return "\n".join(pages)
        except Exception:
            logger.warning("Failed to extract text from PDF: %s", file_path)
            return ""

    logger.warning("Unsupported file type for text extraction: %s", file_path)
    return ""


async def extract_pdf_pages(file_path: str) -> list[str]:
    """Extract text from a PDF as a list of per-page strings.

    Returns empty list for non-PDF or on error.
    """
    if not file_path.lower().endswith(".pdf"):
        return []
    try:
        return _read_pdf_pages(file_path)
    except Exception:
        logger.warning("Failed to extract PDF pages: %s", file_path)
        return []


def _clean_text(text: str) -> str:
    """Remove tracking URLs, ad links, and noise from extracted text."""
    # Remove URLs (http/https/www patterns)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+", "", text)
    # Collapse multiple whitespace/newlines into single
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


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


# intfloat/multilingual-e5-large-instruct has a 512 token limit.
# Turkish text tokenizes at ~2.5 chars/token → 512 * 2.5 ≈ 1280.
# Use 1000 chars as safe limit.
_MAX_CHUNK_CHARS = 1000


async def _build_chunks(file_path: str) -> list[str]:
    """Build chunks from a file.

    PDFs: page-based chunking — each page becomes one chunk.
    If a page exceeds the embedding model's token limit, it is split further
    with overlap so neighbouring sub-chunks share context.
    Other files: fixed-size text splitting.
    """
    if file_path.lower().endswith(".pdf"):
        pages = await extract_pdf_pages(file_path)
        chunks: list[str] = []
        for page_text in pages:
            cleaned = _clean_text(page_text)
            if not cleaned:
                continue
            if len(cleaned) > _MAX_CHUNK_CHARS:
                sub_chunks = await chunk_text(
                    cleaned, chunk_size=_MAX_CHUNK_CHARS, overlap=300
                )
                chunks.extend(sub_chunks)
            else:
                chunks.append(cleaned)
        return chunks

    raw_text = await extract_text_from_file(file_path)
    text = _clean_text(raw_text)
    if not text:
        return []
    return await chunk_text(text, chunk_size=_MAX_CHUNK_CHARS, overlap=200)


async def index_document(
    db: AsyncSession,
    ai_client: TogetherAIClient,
    document_id: uuid.UUID,
) -> int:
    """Index a document for RAG search.

    PDFs are chunked page-by-page to keep logical sections intact.
    Other files are split into 1500-char chunks with overlap.

    Returns:
        Number of chunks created.
    """
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        return 0

    chunks = await _build_chunks(document.file_path)
    if not chunks:
        return 0

    # Embed in batches of 50 to stay within API limits
    all_embeddings: list[list[float]] = []
    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        batch_embeddings = await ai_client.embed(batch)
        all_embeddings.extend(batch_embeddings)

    for idx, (chunk_text_content, embedding) in enumerate(zip(chunks, all_embeddings)):
        chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=idx,
            content=chunk_text_content,
            embedding=json.dumps(embedding),
        )
        db.add(chunk)

    await db.flush()
    return len(chunks)


def _merge_adjacent_chunks(
    top_results: list[dict],
    all_chunks_by_doc: dict[uuid.UUID, list],
) -> list[dict]:
    """Merge top results with their adjacent chunks from the same document.

    When a hit is found at chunk_index N, also include N-1 and N+1 to
    provide full context (e.g. a full country page that spans two chunks).
    """
    merged: list[dict] = []
    seen_keys: set[tuple[uuid.UUID, int]] = set()

    for result in top_results:
        doc_id = result["document_id"]
        chunk_index = result["chunk_index"]
        doc_chunks = all_chunks_by_doc.get(doc_id, [])
        if not doc_chunks:
            merged.append(result)
            continue

        # Gather this chunk and its neighbors
        indices_to_merge = []
        for offset in (-1, 0, 1):
            idx = chunk_index + offset
            if idx < 0:
                continue
            key = (doc_id, idx)
            if key not in seen_keys:
                # Find chunk with this index
                for c in doc_chunks:
                    if c.chunk_index == idx:
                        indices_to_merge.append((idx, c.content))
                        seen_keys.add(key)
                        break

        if not indices_to_merge:
            merged.append(result)
            continue

        indices_to_merge.sort(key=lambda x: x[0])
        combined_content = "\n".join(text for _, text in indices_to_merge)

        merged.append({
            "content": combined_content,
            "score": result["score"],
            "document_id": doc_id,
        })

    return merged


async def search_similar(
    db: AsyncSession,
    ai_client: TogetherAIClient,
    query: str,
    case_id: uuid.UUID | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Search for similar document chunks with adjacent-chunk merging.

    1. Embed the query
    2. Load document_chunks (optionally filtered by case_id via document)
    3. Compute cosine similarity in Python
    4. Merge adjacent chunks from the same document for fuller context
    5. Return top_k results sorted by score descending.

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

    # Build index for merging
    chunks_by_doc: dict[uuid.UUID, list] = {}
    for chunk in all_chunks:
        chunks_by_doc.setdefault(chunk.document_id, []).append(chunk)

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
                "chunk_index": chunk.chunk_index,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    top_results = scored[:top_k]

    # Merge adjacent chunks for fuller context
    merged = _merge_adjacent_chunks(top_results, chunks_by_doc)

    # Remove internal chunk_index from final output
    for item in merged:
        item.pop("chunk_index", None)

    return merged


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

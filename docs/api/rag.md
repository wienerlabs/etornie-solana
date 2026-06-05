# RAG pipeline (`/ai`)

Etornie's document Q&A is a retrieval-augmented-generation (RAG)
pipeline: case documents are **indexed** into vector embeddings, a
question is matched against the most relevant chunks, and an LLM answers
**grounded in those chunks** (with sources). It powers the case
assistant.

All three operations require an authenticated caller who can access the
document's case (admin, or the bound client).

## 1. Index a document

```http
POST /ai/index/{document_id}
Authorization: Bearer <access_token>
```

→ `{ "chunks_created": 12 }`

Under the hood (`app/ai/rag/service.py`):

1. **Extract text** from the stored file (PDFs are read page-by-page;
   `.txt`/`.md` directly).
2. **Clean + chunk** — PDFs are chunked page-by-page; long pages are
   split with overlap to stay within the embedding model's token limit.
3. **Embed** each chunk with Together AI
   (`intfloat/multilingual-e5-large-instruct`), in batches.
4. **Store** each chunk + its embedding as a `DocumentChunk` row
   (Postgres + pgvector).

Re-indexing a document adds fresh chunks; `chunks_created` is `0` when
there is no extractable text (e.g. an empty or unsupported file).

## 2. Semantic search

```http
POST /ai/search
Authorization: Bearer <access_token>
Content-Type: application/json

{ "query": "what is the filing deadline?", "case_id": "<uuid>", "top_k": 5 }
```

Response:

```json
{
  "results": [
    { "content": "…matching chunk text…", "score": 0.83, "document_id": "<uuid>" }
  ]
}
```

- `case_id` (optional) scopes the search to one case's documents.
- `top_k` (1–50, default 5) caps the number of hits.
- The top hits are returned with their neighbouring chunks merged in, so
  a section that spans two chunks comes back whole.

## 3. Ask a question (chat)

```http
POST /ai/rag/chat
Authorization: Bearer <access_token>
Content-Type: application/json

{ "question": "which documents are still required?", "case_id": "<uuid>" }
```

Response:

```json
{
  "answer": "…grounded answer…",
  "sources": [
    { "content": "…chunk used as context…", "score": 0.81, "document_id": "<uuid>" }
  ]
}
```

The endpoint searches the case's indexed chunks, injects the best
matches as context, and asks the LLM to answer using only that context —
returning both the `answer` and the `sources` it relied on. If nothing
relevant is indexed, the assistant says so rather than inventing facts.

## Notes

- Embeddings need `TOGETHER_API_KEY`; without it, indexing/search/chat
  return errors (the feature is opt-in via config).
- Indexing is currently an explicit call (`POST /ai/index/{id}`), not
  automatic on upload — index a document before expecting the assistant
  to answer from it.

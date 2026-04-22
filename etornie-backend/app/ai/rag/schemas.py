"""Pydantic schemas for RAG endpoints."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    query: str
    case_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class SearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str
    score: float
    document_id: uuid.UUID


class SearchResponse(BaseModel):
    results: list[SearchResult]


class ChatRequest(BaseModel):
    question: str
    case_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SearchResult]


class IndexResponse(BaseModel):
    chunks_created: int

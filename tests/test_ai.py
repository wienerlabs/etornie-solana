"""Tests for the AI / RAG module."""

import json
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import TogetherAIClient, get_ai_client
from app.ai.rag.models import DocumentChunk
from app.ai.rag.service import chunk_text, extract_text_from_file, index_document
from app.cases.service import create_case
from app.documents.service import create_document
from app.main import app
from app.users.models import User

from tests.conftest import auth_headers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ai_client() -> AsyncMock:
    """Return a mock TogetherAIClient with canned responses."""
    client = AsyncMock(spec=TogetherAIClient)
    client.chat.return_value = "This is a mock AI response."
    # Return a list of embedding vectors (one per input text)
    client.embed.return_value = [[0.1, 0.2, 0.3, 0.4, 0.5]]
    client.close.return_value = None
    return client


@pytest.fixture
async def document_with_file(
    db_session: AsyncSession,
    case_fixture,  # noqa: ANN001
    lawyer_user: User,
) -> tuple:
    """Create a Document record + an actual temp file for indexing tests.

    Returns (document, file_path).
    """
    content = "This is test document content for RAG indexing. " * 20
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()

    document = await create_document(
        db_session,
        case_id=case_fixture.id,
        uploaded_by=lawyer_user.id,
        filename="test_doc.txt",
        file_path=tmp.name,
        file_type="text/plain",
        file_size=len(content),
    )

    yield document, tmp.name

    # Cleanup
    if os.path.exists(tmp.name):
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Unit tests — AI client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_client_chat_sends_correct_request() -> None:
    """Unit test: TogetherAIClient.chat sends the right payload."""
    # Use MagicMock for response since httpx.Response.json() is synchronous
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello from AI"}}]
    }

    instance = AsyncMock()
    instance.post.return_value = mock_response

    client = TogetherAIClient(
        api_key="test-key",
        model="test-model",
        embedding_model="test-embed-model",
    )
    # Replace the internal _http with our mock
    client._http = instance

    result = await client.chat(
        [{"role": "user", "content": "Hi"}],
        temperature=0.5,
        max_tokens=512,
    )

    assert result == "Hello from AI"
    instance.post.assert_called_once_with(
        "/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.5,
            "max_tokens": 512,
        },
        timeout=30.0,
    )


@pytest.mark.asyncio
async def test_ai_client_embed_sends_correct_request() -> None:
    """Unit test: TogetherAIClient.embed sends the right payload."""
    # Use MagicMock for response since httpx.Response.json() is synchronous
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    }

    instance = AsyncMock()
    instance.post.return_value = mock_response

    client = TogetherAIClient(
        api_key="test-key",
        model="test-model",
        embedding_model="test-embed-model",
    )
    client._http = instance

    result = await client.embed(["hello world"])

    assert result == [[0.1, 0.2, 0.3]]
    instance.post.assert_called_once_with(
        "/embeddings",
        json={
            "model": "test-embed-model",
            "input": ["hello world"],
        },
        timeout=15.0,
    )


# ---------------------------------------------------------------------------
# Unit tests — chunking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_text_splits_correctly() -> None:
    """chunk_text splits text into correct number of chunks."""
    text = "a" * 1200  # 1200 chars
    chunks = await chunk_text(text, chunk_size=500, overlap=0)
    assert len(chunks) == 3
    assert chunks[0] == "a" * 500
    assert chunks[1] == "a" * 500
    assert chunks[2] == "a" * 200


@pytest.mark.asyncio
async def test_chunk_text_with_overlap() -> None:
    """chunk_text produces overlapping chunks."""
    text = "a" * 1000
    chunks = await chunk_text(text, chunk_size=500, overlap=50)
    # First chunk: [0:500], second chunk starts at 450: [450:950], third at 900: [900:1000]
    assert len(chunks) == 3
    assert len(chunks[0]) == 500
    assert len(chunks[1]) == 500
    assert len(chunks[2]) == 100


@pytest.mark.asyncio
async def test_chunk_text_empty_input() -> None:
    """chunk_text returns empty list for empty input."""
    chunks = await chunk_text("")
    assert chunks == []
    chunks = await chunk_text("   ")
    assert chunks == []


# ---------------------------------------------------------------------------
# Unit tests — text extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_text_from_txt_file() -> None:
    """extract_text_from_file reads .txt files."""
    content = "Hello, this is a test document."
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await extract_text_from_file(tmp_path)
        assert result == content
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Endpoint tests — with dependency override for AI client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_endpoint_returns_answer(
    client: AsyncClient,
    admin_user: User,
    mock_ai_client: AsyncMock,
) -> None:
    """POST /ai/chat returns an AI answer when authenticated."""
    app.dependency_overrides[get_ai_client] = lambda: mock_ai_client

    try:
        response = await client.post(
            "/ai/chat",
            json={"question": "What is IP law?"},
            headers=auth_headers(admin_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert data["answer"] == "This is a mock AI response."
        assert "sources" in data
    finally:
        app.dependency_overrides.pop(get_ai_client, None)


@pytest.mark.asyncio
async def test_chat_endpoint_requires_auth(
    client: AsyncClient,
    mock_ai_client: AsyncMock,
) -> None:
    """POST /ai/chat without auth returns 401."""
    app.dependency_overrides[get_ai_client] = lambda: mock_ai_client

    try:
        response = await client.post(
            "/ai/chat",
            json={"question": "What is IP law?"},
        )
        # HTTPBearer returns 403 when no credentials provided
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides.pop(get_ai_client, None)


@pytest.mark.asyncio
async def test_search_endpoint_returns_results(
    client: AsyncClient,
    admin_user: User,
    db_session: AsyncSession,
    document_with_file: tuple,
    mock_ai_client: AsyncMock,
) -> None:
    """POST /ai/search returns results when chunks exist."""
    document, _ = document_with_file

    # Pre-populate a chunk in the DB
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content="Test chunk content about IP law.",
        embedding=json.dumps([0.1, 0.2, 0.3, 0.4, 0.5]),
    )
    db_session.add(chunk)
    await db_session.flush()

    app.dependency_overrides[get_ai_client] = lambda: mock_ai_client

    try:
        response = await client.post(
            "/ai/search",
            json={"query": "IP law"},
            headers=auth_headers(admin_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) >= 1
        assert "content" in data["results"][0]
        assert "score" in data["results"][0]
        assert "document_id" in data["results"][0]
    finally:
        app.dependency_overrides.pop(get_ai_client, None)


@pytest.mark.asyncio
async def test_search_endpoint_requires_auth(
    client: AsyncClient,
    mock_ai_client: AsyncMock,
) -> None:
    """POST /ai/search without auth returns 401."""
    app.dependency_overrides[get_ai_client] = lambda: mock_ai_client

    try:
        response = await client.post(
            "/ai/search",
            json={"query": "test"},
        )
        # HTTPBearer returns 403 when no credentials provided
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides.pop(get_ai_client, None)


@pytest.mark.asyncio
async def test_index_document_creates_chunks(
    client: AsyncClient,
    lawyer_user: User,
    db_session: AsyncSession,
    document_with_file: tuple,
    mock_ai_client: AsyncMock,
) -> None:
    """POST /ai/index/{document_id} creates chunks in the database."""
    document, _ = document_with_file

    # Mock embed to return vectors for each chunk
    mock_ai_client.embed.return_value = [
        [0.1, 0.2, 0.3] for _ in range(20)
    ]

    app.dependency_overrides[get_ai_client] = lambda: mock_ai_client

    try:
        response = await client.post(
            f"/ai/index/{document.id}",
            headers=auth_headers(lawyer_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert "chunks_created" in data
        assert data["chunks_created"] > 0
    finally:
        app.dependency_overrides.pop(get_ai_client, None)


@pytest.mark.asyncio
async def test_index_document_requires_admin_or_lawyer(
    client: AsyncClient,
    client_user: User,
    document_with_file: tuple,
    mock_ai_client: AsyncMock,
) -> None:
    """POST /ai/index/{document_id} as client user returns 403."""
    document, _ = document_with_file

    app.dependency_overrides[get_ai_client] = lambda: mock_ai_client

    try:
        response = await client.post(
            f"/ai/index/{document.id}",
            headers=auth_headers(client_user),
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_ai_client, None)


@pytest.mark.asyncio
async def test_index_nonexistent_document_returns_404(
    client: AsyncClient,
    admin_user: User,
    mock_ai_client: AsyncMock,
) -> None:
    """POST /ai/index/{random_uuid} returns 404."""
    app.dependency_overrides[get_ai_client] = lambda: mock_ai_client

    try:
        random_id = uuid.uuid4()
        response = await client.post(
            f"/ai/index/{random_id}",
            headers=auth_headers(admin_user),
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_ai_client, None)


@pytest.mark.asyncio
async def test_ai_service_unavailable_without_key(
    client: AsyncClient,
    admin_user: User,
) -> None:
    """When together_api_key is empty, AI endpoints return 503."""
    # Remove any override so the real get_ai_client is used
    app.dependency_overrides.pop(get_ai_client, None)

    with patch("app.ai.client.settings") as mock_settings:
        mock_settings.together_api_key = ""
        mock_settings.together_model = "test-model"
        mock_settings.together_embedding_model = "test-embed-model"

        response = await client.post(
            "/ai/chat",
            json={"question": "test"},
            headers=auth_headers(admin_user),
        )
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

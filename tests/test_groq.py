"""Tests for the Groq / EtornieGPT integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.ai.groq_client import GroqClient, IP_SYSTEM_PROMPT, get_groq_client
from app.main import app
from app.users.models import User

from tests.conftest import auth_headers


# ---------------------------------------------------------------------------
# Unit tests -- GroqClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_client_chat_sends_correct_request() -> None:
    """GroqClient.chat sends the right payload with system prompt."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "This is a trademark question..."}}]
    }

    mock_http = AsyncMock()
    mock_http.post.return_value = mock_response

    client = GroqClient(api_key="test-key", model="llama-3.3-70b-versatile")
    client._http = mock_http

    result = await client.chat(
        messages=[{"role": "user", "content": "What is a trademark?"}],
        system_prompt="You are a helpful assistant.",
    )

    assert result == "This is a trademark question..."
    mock_http.post.assert_called_once()
    call_kwargs = mock_http.post.call_args
    payload = call_kwargs.kwargs["json"]
    assert payload["model"] == "llama-3.3-70b-versatile"
    assert payload["messages"][0] == {
        "role": "system",
        "content": "You are a helpful assistant.",
    }
    assert payload["messages"][1] == {
        "role": "user",
        "content": "What is a trademark?",
    }


@pytest.mark.asyncio
async def test_groq_client_chat_without_system_prompt() -> None:
    """GroqClient.chat works without a system prompt (no system message prepended)."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello!"}}]
    }

    mock_http = AsyncMock()
    mock_http.post.return_value = mock_response

    client = GroqClient(api_key="test-key", model="test-model")
    client._http = mock_http

    result = await client.chat(
        messages=[{"role": "user", "content": "Hi"}],
    )

    assert result == "Hello!"
    payload = mock_http.post.call_args.kwargs["json"]
    # No system message should be present
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"


# ---------------------------------------------------------------------------
# Endpoint tests -- /ai/chat with Groq
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_chat_endpoint_returns_answer(
    client: AsyncClient,
    admin_user: User,
) -> None:
    """POST /ai/chat returns an AI answer via Groq when authenticated."""
    mock_groq = AsyncMock(spec=GroqClient)
    mock_groq.chat.return_value = "This is a trademark question..."
    mock_groq.close.return_value = None

    app.dependency_overrides[get_groq_client] = lambda: mock_groq

    try:
        response = await client.post(
            "/ai/chat",
            json={"question": "What is IP law?"},
            headers=auth_headers(admin_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "This is a trademark question..."
        assert "sources" in data
        assert isinstance(data["sources"], list)
    finally:
        app.dependency_overrides.pop(get_groq_client, None)


@pytest.mark.asyncio
async def test_groq_chat_includes_system_prompt(
    client: AsyncClient,
    admin_user: User,
) -> None:
    """POST /ai/chat passes the IP_SYSTEM_PROMPT to the Groq client."""
    mock_groq = AsyncMock(spec=GroqClient)
    mock_groq.chat.return_value = "EtornieGPT response about patents."
    mock_groq.close.return_value = None

    app.dependency_overrides[get_groq_client] = lambda: mock_groq

    try:
        response = await client.post(
            "/ai/chat",
            json={"question": "How do I file a patent?"},
            headers=auth_headers(admin_user),
        )
        assert response.status_code == 200

        # Verify that the system_prompt kwarg was passed containing IP_SYSTEM_PROMPT
        mock_groq.chat.assert_called_once()
        call_kwargs = mock_groq.chat.call_args
        system_prompt_sent = call_kwargs.kwargs.get(
            "system_prompt"
        ) or call_kwargs.args[0] if call_kwargs.args else None

        # Check kwargs specifically
        assert "system_prompt" in call_kwargs.kwargs
        assert IP_SYSTEM_PROMPT in call_kwargs.kwargs["system_prompt"]
    finally:
        app.dependency_overrides.pop(get_groq_client, None)


@pytest.mark.asyncio
async def test_groq_chat_requires_auth(
    client: AsyncClient,
) -> None:
    """POST /ai/chat without auth returns 401/403."""
    mock_groq = AsyncMock(spec=GroqClient)
    mock_groq.chat.return_value = "Should not reach here."
    mock_groq.close.return_value = None

    app.dependency_overrides[get_groq_client] = lambda: mock_groq

    try:
        response = await client.post(
            "/ai/chat",
            json={"question": "What is IP law?"},
        )
        # HTTPBearer returns 403 when no credentials provided
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides.pop(get_groq_client, None)


@pytest.mark.asyncio
async def test_groq_unavailable_without_key(
    client: AsyncClient,
    admin_user: User,
) -> None:
    """When groq_api_key is empty, /ai/chat returns 503."""
    # Remove any override so the real get_groq_client is used
    app.dependency_overrides.pop(get_groq_client, None)

    with patch("app.ai.groq_client.settings") as mock_settings:
        mock_settings.groq_api_key = ""
        mock_settings.groq_model = "llama-3.3-70b-versatile"

        response = await client.post(
            "/ai/chat",
            json={"question": "test"},
            headers=auth_headers(admin_user),
        )
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

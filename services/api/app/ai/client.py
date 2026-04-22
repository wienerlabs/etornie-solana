"""Async client for Together AI REST API."""

import logging

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.together.xyz/v1"


class TogetherAIClient:
    """Async client for Together AI API."""

    def __init__(self, api_key: str, model: str, embedding_model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._embedding_model = embedding_model
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """Send chat completion request. Returns the assistant's response text."""
        try:
            response = await self._http.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="AI service request timed out",
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Together AI chat error: %s", exc.response.text)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI service returned an error",
            )
        except httpx.HTTPError as exc:
            logger.error("Together AI connection error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to AI service",
            )

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts. Returns list of embedding vectors."""
        try:
            response = await self._http.post(
                "/embeddings",
                json={
                    "model": self._embedding_model,
                    "input": texts,
                },
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="AI embedding request timed out",
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Together AI embed error: %s", exc.response.text)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI embedding service returned an error",
            )
        except httpx.HTTPError as exc:
            logger.error("Together AI connection error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to AI embedding service",
            )

        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()


def get_ai_client() -> TogetherAIClient:
    """FastAPI dependency that returns the AI client. Raises 503 if API key not configured."""
    if not settings.together_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service not configured",
        )
    return TogetherAIClient(
        api_key=settings.together_api_key,
        model=settings.together_model,
        embedding_model=settings.together_embedding_model,
    )

"""Groq LLM client for EtornieGPT — IP law assistant."""

import logging

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.groq.com/openai/v1"

# System prompt that specializes the AI in IP law
IP_SYSTEM_PROMPT = """You are EtornieGPT, an AI assistant specialized in Intellectual Property (IP) law and patent services for Etornie, a professional IP services firm.

Your areas of expertise:
1. **Trademarks**: Registration, opposition, renewal, international protection (Madrid Protocol), distinctiveness assessment, likelihood of confusion analysis
2. **Patents**: Patent filing procedures, patentability assessment (novelty, inventive step, industrial applicability), PCT applications, EPO/EUIPO/USPTO processes, patent claims drafting guidance
3. **Industrial Designs**: Design registration, design novelty, Hague System, protection scope
4. **Copyright**: Copyright registration, licensing, fair use, digital rights, software copyright
5. **IP Strategy**: Portfolio management, freedom-to-operate analysis, IP valuation, licensing strategies, IP due diligence
6. **IP Offices**: Procedures at Turkish Patent and Trademark Office (TURKPATENT), European Patent Office (EPO), European Union Intellectual Property Office (EUIPO), United States Patent and Trademark Office (USPTO)
7. **IP Litigation**: Infringement analysis, cease and desist procedures, opposition proceedings, invalidation actions

Guidelines:
- Always provide accurate, professional advice based on current IP law practices
- When discussing jurisdiction-specific matters, clarify which jurisdiction applies
- If a question is outside your IP expertise, politely redirect to the relevant domain
- Use clear, concise language suitable for both legal professionals and clients
- When appropriate, suggest next steps or actions the user should take
- Reference relevant treaties and agreements (Paris Convention, TRIPS, Madrid Protocol, PCT, etc.)
- Always recommend consulting with a qualified IP attorney for specific legal decisions

You respond in the same language as the user's question. If they write in Turkish, respond in Turkish. If in English, respond in English."""


class GroqClient:
    """Async client for Groq API (OpenAI-compatible)."""

    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self.base_url = _BASE_URL
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ) -> str:
        """Send chat completion request. Returns the assistant's response text."""
        full_messages: list[dict] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = await self._http.post(
                "/chat/completions",
                json=payload,
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Groq API request timed out",
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to Groq API",
            )

        if not response.is_success:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
            except Exception:
                error_msg = response.text
            logger.error("Groq API error (%s): %s", response.status_code, error_msg)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Groq API error: {error_msg}",
            )

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()


def get_groq_client() -> GroqClient:
    """FastAPI dependency. Raises 503 if not configured."""
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="EtornieGPT AI service not configured",
        )
    return GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
    )

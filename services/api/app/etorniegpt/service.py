"""EtornieGPT service: country-aware IP law assistant powered by Together AI."""

import re

from together import Together

from app.config import settings
from app.etorniegpt.countries import (
    detect_country_from_question,
    format_country_context,
    _normalize,
    _ALIASES,
)

SYSTEM_PROMPT = (
    "You are EtornieGPT, an AI assistant for an IP (intellectual property) management "
    "platform. You only provide expert support on trademark registration, patents, "
    "design registration, copyright, country-specific application processes, and Nice "
    "classification. You do not answer questions outside these areas. Provide short and "
    "clear answers, do not use emojis, do not fabricate information, and respond in the "
    "same language the question is asked in. If you do not have the information, say "
    "'I do not have this information', never fabricate."
)

MODEL = "openai/gpt-oss-20b"

# Known country name patterns to detect "country mentioned but not in DB"
_COUNTRY_INDICATORS = [
    " in ", " of ",
    " about ", " regarding ",
    "country", "jurisdiction",
]


def _question_mentions_unknown_country(question: str) -> bool:
    """Check if question likely asks about a specific country not in our DB."""
    normalized = _normalize(question)

    # If detect_country found something, it's not unknown
    # This function is only called when detect returns None
    # Check if there are country-like patterns
    for indicator in _COUNTRY_INDICATORS:
        if indicator in question.lower() or _normalize(indicator) in normalized:
            return True

    return False


def _build_messages(question: str) -> tuple[list[dict], str | None]:
    """Build message list for the LLM.

    Returns (messages, country_name_or_none).
    Country data goes into user message, not system prompt.
    """
    country = detect_country_from_question(question)

    if country is not None:
        # Country found in DB — inject data into user message
        country_context = format_country_context(country)
        country_name = country.get("country", "Unknown")

        user_content = (
            f"Question: {question}\n\n"
            f"Verified data for this country:\n"
            f"{country_context}\n\n"
            f"Answer ONLY using the data above. "
            f"Do not go beyond this data. If information not present in the data is asked, "
            f"say 'This information is not available in our database'."
        )

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ], country_name

    # No country detected — return plain question
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ], None


async def ask_etorniegpt(question: str, language: str = "tr") -> dict:
    """Send a question to EtornieGPT and return the answer.

    Returns dict with keys: answer, country_detected, model.
    """
    messages, country_name = _build_messages(question)

    # If no country detected but question seems country-specific,
    # return hardcoded "not in DB" response without calling LLM
    if country_name is None and _question_mentions_unknown_country(question):
        return {
            "answer": "No information about this country is available in our database.",
            "country_detected": None,
            "model": MODEL,
        }

    client = Together(api_key=settings.together_api_key)

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=1024,
        temperature=0.3,
    )

    answer = response.choices[0].message.content or ""

    return {
        "answer": answer,
        "country_detected": country_name,
        "model": MODEL,
    }

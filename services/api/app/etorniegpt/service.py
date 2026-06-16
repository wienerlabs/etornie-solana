"""EtornieGPT service: country-aware IP law assistant powered by Together AI."""

import logging
import re

from together import Together

from app.config import settings
from app.errors import ErrorCategory, UserFacingError
from app.etorniegpt.countries import (
    detect_country_from_question,
    format_country_context,
    _normalize,
    _ALIASES,
    _IGNORE_TERMS,
)

SYSTEM_PROMPT = (
    "You are EtornieGPT, the AI assistant of Etornie - a platform that "
    "classifies, prepares, files and tracks intellectual-property rights "
    "(trademarks, patents, designs, copyright) for its users.\n\n"
    "Scope: only answer IP topics - registration/filing, copyright, Nice "
    "classification, country-specific procedures, and how Etornie's own "
    "process works. Politely decline anything outside IP.\n\n"
    "Etornie does the work for the user - guide the user through Etornie, "
    "not national offices:\n"
    "- Etornie's AI agent prepares and submits the application to the "
    "relevant IP office (e.g. EUIPO) on the user's behalf; the user does not "
    "file at the national office themselves.\n"
    "- Help pick the correct Nice class(es) and goods/services, list the "
    "required documents, and explain each step of the Etornie flow: open a "
    "case, classify, prepare the application, pay inside Etornie (by card via "
    "Stripe, or with crypto via Solana), the agent files it, track the "
    "status, and get on-chain proof of the filing on Solana.\n"
    "- When asked 'how do I register/file', explain the process and direct "
    "the user to do it through Etornie; do not present going to the national "
    "office directly as the primary route.\n\n"
    "Accuracy: never fabricate. For exact fees, timelines or amounts, do not "
    "invent numbers - say they are shown in the user's Etornie case or "
    "checkout. If you do not have the information, say 'I do not have this "
    "information'.\n\n"
    "Style: clear and concise, no emojis, and always reply in the same "
    "language the question is asked in."
)

logger = logging.getLogger(__name__)

MODEL = settings.together_etorniegpt_model

# A locative preposition immediately followed by a capitalised proper noun
# ("in Turkey", "of Brazil", "about Chile") is the signal that the user is
# asking about a specific place. Matched on word boundaries against the
# original (case-bearing) text.
_PLACE_CONTEXT_RE = re.compile(
    r"\b(?:[Ii]n|[Oo]f|[Aa]bout|[Rr]egarding)\s+(?:the\s+)?([A-Z][A-Za-z]+)"
)


def _question_mentions_unknown_country(question: str) -> bool:
    """True when the question targets a specific named place we cannot resolve.

    Only reached when ``detect_country_from_question`` already failed, so a
    capitalised proper noun after a locative preposition is a country /
    jurisdiction we have no verified data for (e.g. "...registration in
    Turkey?").

    Crucially this matches whole words: ordinary words like "international",
    "software" or "single" never trigger it. The previous implementation
    substring-matched the "in"/"of" *inside* those words and wrongly returned
    the "no data" canned answer for almost every general question. Known IP
    terms / organisations (Madrid, Nice, WIPO, ...) are excluded.
    """
    for match in _PLACE_CONTEXT_RE.finditer(question):
        candidate = _normalize(match.group(1))
        if candidate and candidate not in _IGNORE_TERMS:
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

    # Any upstream model failure (credit/rate limit, timeout, 5xx, bad
    # config) is surfaced as a clean 502 via UserFacingError instead of a
    # raw 500, so callers — the chat UI and the partner /api/v1/chat — get a
    # friendly message they can show and retry on.
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1024,
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001 — surface every upstream failure cleanly
        logger.error("EtornieGPT model call failed (model=%s): %s", MODEL, exc)
        raise UserFacingError(
            "The assistant is temporarily unavailable. Please try again in a moment.",
            technical_detail=f"{type(exc).__name__}: {exc}",
            category=ErrorCategory.unknown,
            http_status=502,
        ) from exc

    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        logger.warning("EtornieGPT returned an empty completion (model=%s)", MODEL)
        raise UserFacingError(
            "The assistant could not generate an answer. Please rephrase your "
            "question and try again.",
            technical_detail="empty completion content",
            category=ErrorCategory.unknown,
            http_status=502,
        )

    return {
        "answer": answer,
        "country_detected": country_name,
        "model": MODEL,
    }

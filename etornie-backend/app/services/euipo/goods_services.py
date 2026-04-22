"""EUIPO Goods and Services API service.

Validates and classifies Nice class terms for trademark filings.
Auth: client_credentials (scope: uid).
Rate limit: 1,000 calls/hour.
"""

from typing import Any

from app.services.euipo.client import euipo_request

_RATE_GROUP = "goods_services"
_BASE_PATH = "/goods-and-services"


async def search_terms(
    *,
    query: str,
    nice_class: int | None = None,
    language: str = "en",
    page: int = 0,
    page_size: int = 20,
) -> dict[str, Any]:
    """Search for goods/services terms in the EUIPO TMClass taxonomy.

    Args:
        query: Term to search for.
        nice_class: Filter by specific Nice class (1-45).
        language: ISO language code (default "en").
        page: Page number (0-based).
        page_size: Results per page.

    Returns:
        Matching terms with their Nice classification.
    """
    params: dict[str, Any] = {
        "termText": query,
        "language": language,
        "page": page,
        "size": min(page_size, 100),
    }
    if nice_class is not None:
        params["classNumber"] = nice_class

    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/terms",
        rate_group=_RATE_GROUP,
        params=params,
    )


async def validate_classification(
    goods_and_services: list[dict[str, Any]],
    *,
    source_language: str = "en",
) -> dict[str, Any]:
    """Validate a goods/services classification against EUIPO standards.

    Args:
        goods_and_services: List of {"classNumber": int, "terms": ["term1", ...]}.
        source_language: Language code of the terms.

    Returns:
        Validation result with accepted/rejected terms.
    """
    return await euipo_request(
        "POST",
        f"{_BASE_PATH}/classification-validation",
        rate_group=_RATE_GROUP,
        json_body={
            "sourceLanguage": source_language,
            "goodsAndServices": goods_and_services,
        },
    )


async def translate_classification(
    goods_and_services: list[dict[str, Any]],
    *,
    source_language: str = "en",
    target_languages: list[str],
) -> dict[str, Any]:
    """Translate goods/services terms to other EU languages.

    Args:
        goods_and_services: List of {"classNumber": int, "terms": ["term1", ...]}.
        source_language: Source language code.
        target_languages: Target language codes (e.g. ["es", "de", "fr"]).

    Returns:
        Translated terms per language.
    """
    return await euipo_request(
        "POST",
        f"{_BASE_PATH}/classification-translation",
        rate_group=_RATE_GROUP,
        json_body={
            "sourceLanguage": source_language,
            "languagesToTranslate": target_languages,
            "goodsAndServices": goods_and_services,
        },
    )


async def get_class_headings(
    *,
    language: str = "en",
) -> dict[str, Any]:
    """Get official Nice class headings.

    Args:
        language: Language code.

    Returns:
        All 45 class headings.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/classHeadings",
        rate_group=_RATE_GROUP,
        params={"language": language},
    )


async def get_term_suggestions(
    terms: list[str],
    *,
    language: str = "en",
) -> dict[str, Any]:
    """Get suggestions for goods/services terms.

    Args:
        terms: List of term strings to get suggestions for.
        language: Language code.

    Returns:
        Suggested terms per input.
    """
    return await euipo_request(
        "POST",
        f"{_BASE_PATH}/terms-suggestion-list",
        rate_group=_RATE_GROUP,
        json_body={"language": language, "terms": terms},
    )

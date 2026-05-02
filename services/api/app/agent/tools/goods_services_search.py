"""goods_services_search tool — search the EUIPO TMClass taxonomy.

Wraps :func:`app.services.euipo.goods_services.search_terms` so the
agent can look up which Nice class covers a given goods/services term
without leaving the chat surface. Trims the upstream payload to the
fields the model actually needs to reason over.
"""
from __future__ import annotations

from typing import Any

from app.agent.tools.base import Tool, ToolError, register
from app.services.euipo.client import EUIPOClientError
from app.services.euipo.goods_services import search_terms

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "The goods or services term to search for "
                "(e.g. 'leather goods', 'software development')."
            ),
        },
        "nice_class": {
            "type": "integer",
            "minimum": 1,
            "maximum": 45,
            "description": (
                "Optional Nice class filter (1-45). When omitted, the "
                "search returns matches across all classes."
            ),
        },
        "language": {
            "type": "string",
            "description": (
                "ISO language code for the term language (default 'en'). "
                "EUIPO supports the major EU languages."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "Maximum number of results to return (default 20).",
        },
    },
    "additionalProperties": False,
    "required": ["query"],
}


def _trim_term(term: dict[str, Any]) -> dict[str, Any]:
    return {
        "term_text": term.get("termText") or term.get("text"),
        "class_number": term.get("classNumber"),
        "term_id": term.get("termId") or term.get("id"),
        "language": term.get("language"),
        "status": term.get("status"),
    }


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query is required and must be a non-empty string")

    nice_class = args.get("nice_class")
    if nice_class is not None and not isinstance(nice_class, int):
        raise ToolError("nice_class must be an integer between 1 and 45")
    if isinstance(nice_class, int) and (nice_class < 1 or nice_class > 45):
        raise ToolError("nice_class must be between 1 and 45")

    language = args.get("language") or "en"
    if not isinstance(language, str) or len(language) > 5:
        raise ToolError("language must be a short ISO code, e.g. 'en'")

    limit = args.get("limit") or 20
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ToolError("limit must be an integer between 1 and 50")

    try:
        raw = await search_terms(
            query=query.strip(),
            nice_class=nice_class,
            language=language,
            page=0,
            page_size=limit,
        )
    except EUIPOClientError as exc:
        raise ToolError(f"EUIPO Goods & Services search failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"EUIPO Goods & Services call crashed: {exc}") from exc

    items = raw.get("content") or raw.get("terms") or []
    trimmed = [_trim_term(item) for item in items if isinstance(item, dict)]
    total = raw.get("totalElements") or raw.get("total") or len(trimmed)

    return {
        "query": query.strip(),
        "nice_class": nice_class,
        "language": language,
        "total": total,
        "results": trimmed,
    }


goods_services_search_tool = register(
    Tool(
        name="goods_services_search",
        description=(
            "Search the EUIPO TMClass taxonomy for goods/services terms "
            "and the Nice classes that cover them. Use BEFORE choosing "
            "Nice classes for a trademark filing, so the user picks "
            "EUIPO-accepted wording from the start."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

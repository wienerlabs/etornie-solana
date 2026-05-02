"""goods_services_validate tool — confirm Nice classification with EUIPO.

Wraps :func:`app.services.euipo.goods_services.validate_classification`
so the agent can submit the user's chosen wording (per Nice class) to
EUIPO before filing and surface any rejected terms back to the user
with a chance to correct them.
"""
from __future__ import annotations

from typing import Any

from app.agent.tools.base import Tool, ToolError, register
from app.services.euipo.client import EUIPOClientError
from app.services.euipo.goods_services import validate_classification

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "class_number": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 45,
                        "description": "Nice class number (1-45).",
                    },
                    "terms": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                        "description": (
                            "Goods/services terms the user wants in this class."
                        ),
                    },
                },
                "additionalProperties": False,
                "required": ["class_number", "terms"],
            },
            "description": (
                "Per-class breakdown of goods and services to validate."
            ),
        },
        "source_language": {
            "type": "string",
            "description": (
                "ISO language code of the supplied terms (default 'en')."
            ),
        },
    },
    "additionalProperties": False,
    "required": ["items"],
}


def _normalize_items(items_raw: Any) -> list[dict[str, Any]]:
    if not isinstance(items_raw, list) or not items_raw:
        raise ToolError("items must be a non-empty array")

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(items_raw):
        if not isinstance(entry, dict):
            raise ToolError(f"items[{index}] must be an object")
        class_number = entry.get("class_number")
        terms = entry.get("terms")
        if not isinstance(class_number, int) or class_number < 1 or class_number > 45:
            raise ToolError(
                f"items[{index}].class_number must be an integer between 1 and 45"
            )
        if not isinstance(terms, list) or not terms:
            raise ToolError(
                f"items[{index}].terms must be a non-empty array of strings"
            )
        cleaned_terms: list[str] = []
        for term_index, term in enumerate(terms):
            if not isinstance(term, str) or not term.strip():
                raise ToolError(
                    f"items[{index}].terms[{term_index}] must be a non-empty string"
                )
            cleaned_terms.append(term.strip())
        normalized.append({"classNumber": class_number, "terms": cleaned_terms})
    return normalized


def _trim_validation(result: dict[str, Any]) -> dict[str, Any]:
    items = result.get("goodsAndServices") or result.get("items") or []
    trimmed_items: list[dict[str, Any]] = []
    accepted_count = 0
    rejected_count = 0
    for entry in items:
        if not isinstance(entry, dict):
            continue
        validations = entry.get("termValidations") or entry.get("terms") or []
        out_terms: list[dict[str, Any]] = []
        for term in validations:
            if not isinstance(term, dict):
                continue
            term_text = term.get("termText") or term.get("text")
            status = term.get("status") or term.get("validationStatus")
            reason = term.get("reason") or term.get("message")
            out_terms.append(
                {
                    "term_text": term_text,
                    "status": status,
                    "reason": reason,
                }
            )
            if status and status.upper().startswith("ACCEPT"):
                accepted_count += 1
            elif status and status.upper().startswith("REJECT"):
                rejected_count += 1
        trimmed_items.append(
            {
                "class_number": entry.get("classNumber"),
                "terms": out_terms,
            }
        )

    return {
        "items": trimmed_items,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "ok": rejected_count == 0,
    }


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    items = _normalize_items(args.get("items"))
    source_language = args.get("source_language") or "en"
    if not isinstance(source_language, str) or len(source_language) > 5:
        raise ToolError("source_language must be a short ISO code, e.g. 'en'")

    try:
        raw = await validate_classification(
            items, source_language=source_language
        )
    except EUIPOClientError as exc:
        raise ToolError(
            f"EUIPO Goods & Services validation failed: {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            f"EUIPO Goods & Services validation crashed: {exc}"
        ) from exc

    return _trim_validation(raw)


goods_services_validate_tool = register(
    Tool(
        name="goods_services_validate",
        description=(
            "Validate the user's chosen goods/services wording (per Nice "
            "class) against EUIPO's accepted classification. Returns a "
            "per-term verdict so rejected terms can be reworded BEFORE "
            "submit_filing. Use AFTER goods_services_search and BEFORE "
            "starting any filing robot."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

"""trademark_search tool — wraps the existing EUIPO search service.

This is the first tool in the agent orchestrator. It exists so we can
prove the end-to-end tool-calling loop without rebuilding any of the
legacy EUIPO integration.
"""
from typing import Any

from app.agent.tools.base import Tool, ToolError, register
from app.services.euipo.trademark_search import search_trademarks

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mark_text": {
            "type": "string",
            "description": "The trademark text to search for.",
        },
        "jurisdiction": {
            "type": "string",
            "enum": ["EUIPO", "WIPO", "USPTO", "UKIPO"],
            "description": (
                "The IP office to search in. Defaults to EUIPO when "
                "omitted; only EUIPO is wired up at this milestone."
            ),
        },
        "nice_classes": {
            "type": "array",
            "items": {"type": "integer"},
            "description": (
                "Optional Nice classification numbers (1-45). When "
                "omitted the search runs across all 45 classes — use "
                "this for broad discovery queries like 'is this name "
                "taken anywhere?'."
            ),
        },
    },
    "additionalProperties": False,
    "required": ["mark_text"],
}


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    mark_text = args["mark_text"]
    jurisdiction = args.get("jurisdiction") or "EUIPO"
    nice_classes_raw = args.get("nice_classes")

    if jurisdiction != "EUIPO":
        # Only EUIPO is wired up in this Phase 0 milestone. The other
        # jurisdictions return a clear "not yet supported" payload so the
        # model can phrase a graceful explanation to the user.
        raise ToolError(
            f"Trademark search for {jurisdiction} is not yet implemented. "
            "Only EUIPO is supported at this milestone."
        )

    if nice_classes_raw is None:
        # No filter → broad search across every Nice class. EUIPO accepts
        # a missing classNumber filter as "all classes".
        nice_classes: list[int] = []
    else:
        nice_classes = list(nice_classes_raw)
        if any(c < 1 or c > 45 for c in nice_classes):
            raise ToolError(
                "Nice classes must be integers between 1 and 45."
            )

    raw = await search_trademarks(
        mark_text=mark_text,
        nice_classes=nice_classes,
        page_size=10,
    )

    # Trim payload to keep history compact: only fields the model needs
    # to reason about hits.
    trimmed_results = []
    for item in raw.get("trademarks", [])[:10]:
        trimmed_results.append(
            {
                "application_number": item.get("applicationNumber"),
                "verbal_element": item.get("wordMarkSpecification", {}).get(
                    "verbalElement"
                ),
                "status": item.get("status"),
                "nice_classes": item.get("niceClasses"),
                "office": item.get("office"),
            }
        )

    return {
        "jurisdiction": jurisdiction,
        "query": {
            "mark_text": mark_text,
            "nice_classes": nice_classes,
        },
        "total_hits": raw.get("totalElements", 0),
        "results": trimmed_results,
    }


trademark_search_tool = register(
    Tool(
        name="trademark_search",
        description=(
            "Search existing trademarks in a given jurisdiction before "
            "filing. Use BEFORE submit_filing. Returns up to 10 hits."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

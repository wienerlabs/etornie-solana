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
        # Same string-coercion as create_case_draft: the LLM occasionally
        # hands us strings instead of ints.
        nice_classes = []
        for c in nice_classes_raw:
            try:
                nice_classes.append(int(c))
            except (TypeError, ValueError):
                raise ToolError(
                    "Nice class entries must be integers (1-45). "
                    f"Got: {c!r}"
                )
        if any(c < 1 or c > 45 for c in nice_classes):
            raise ToolError(
                "Nice classes must be integers between 1 and 45."
            )

    # EUIPO sandbox occasionally returns 503 on its OAuth token
    # endpoint — that takes the conflict check offline for a few
    # minutes at a time. Retry once with a short backoff to absorb the
    # most common transient blip, then surface a structured
    # ``service_unavailable`` result so the LLM can tell the user
    # exactly what happened and ask whether they want to proceed
    # anyway instead of dying with a raw stack trace.
    import asyncio
    import logging
    _logger = logging.getLogger(__name__)
    raw: dict[str, Any] | None = None
    last_exc: Exception | None = None
    for attempt in (0, 1):
        try:
            raw = await search_trademarks(
                mark_text=mark_text,
                nice_classes=nice_classes,
                page_size=10,
            )
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _logger.warning(
                "trademark_search attempt %d failed: %s: %s",
                attempt,
                type(exc).__name__,
                exc,
            )
            if attempt == 0:
                await asyncio.sleep(1.5)
            continue

    if last_exc is not None or raw is None:
        msg = str(last_exc) if last_exc is not None else "no response"
        return {
            "service_unavailable": True,
            "jurisdiction": jurisdiction,
            "query": {
                "mark_text": mark_text,
                "nice_classes": nice_classes,
            },
            "error_summary": (
                "EUIPO Trademark Search API is temporarily unreachable"
                f" ({type(last_exc).__name__ if last_exc else 'unknown'})."
            ),
            "error_detail_technical": msg[:400],
            "agent_instructions": (
                "Tell the user clearly that the EUIPO Trademark Search "
                "API is temporarily unavailable (this is an upstream "
                "EUIPO outage, not a problem with their filing). Then "
                "ask EXPLICITLY whether they want to proceed with the "
                "filing without the conflict check, or wait and retry. "
                "DO NOT call prepare_payment until the user clearly "
                "confirms they want to proceed without the check."
            ),
        }

    # The EUIPO API can return hits under ``trademarks``, ``content`` or
    # ``items`` depending on sandbox version; check all three so a
    # backend tweak does not silently empty our output.
    hits = (
        raw.get("trademarks")
        or raw.get("content")
        or raw.get("items")
        or []
    )

    # Trim payload to keep history compact: only fields the model needs
    # to reason about hits.
    trimmed_results = []
    for item in hits[:10]:
        verbal = (
            (item.get("wordMarkSpecification") or {}).get("verbalElement")
            or item.get("verbalElement")
        )
        trimmed_results.append(
            {
                "application_number": item.get("applicationNumber"),
                "verbal_element": verbal,
                "status": item.get("status"),
                "filing_date": item.get("applicationDate")
                or item.get("filingDate"),
                "nice_classes": item.get("niceClasses"),
                "office": item.get("officeCode") or item.get("office"),
                "applicant": (
                    ((item.get("applicants") or [{}])[0]).get("name")
                    if item.get("applicants")
                    else None
                ),
            }
        )

    # Flag verbal-element exact matches (case-insensitive) so the LLM
    # can warn the user explicitly. The user may still proceed
    # (different classes, expired prior, etc.) but they deserve to see
    # the conflict before paying.
    needle = (mark_text or "").casefold()
    exact = [
        r for r in trimmed_results
        if (r.get("verbal_element") or "").casefold() == needle
    ]

    total = (
        raw.get("totalElements")
        if raw.get("totalElements") is not None
        else (raw.get("total") if raw.get("total") is not None else len(hits))
    )

    return {
        "jurisdiction": jurisdiction,
        "query": {
            "mark_text": mark_text,
            "nice_classes": nice_classes,
        },
        "total_hits": total,
        "exact_match_count": len(exact),
        "has_exact_match": bool(exact),
        "results": trimmed_results,
        "agent_instructions": (
            "Tell the user how many trademarks were found and whether "
            "any EXACTLY match the proposed mark text. If hits exist, "
            "list the top 3 with status + Nice classes + office. Then "
            "ask the user EXPLICITLY: 'Do you want to proceed with the "
            "filing despite these results?' DO NOT call prepare_payment "
            "until the user confirms in their next message."
        ),
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

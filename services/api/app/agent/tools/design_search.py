"""design_search tool — query the EUIPO Design Search API.

Wraps :func:`app.services.euipo.design_search.search_designs`. The
agent uses it to check for prior registrations in the user's Locarno
class(es) before recommending an EUIPO design filing. We only expose
the high-signal fields and trim the EUIPO payload so the model can
reason about hits without drowning in metadata.
"""
from __future__ import annotations

from typing import Any

from app.agent.tools.base import Tool, ToolError, register
from app.services.euipo.client import EUIPOClientError
from app.services.euipo.design_search import search_designs

_LOCARNO_PATTERN_HINT = "two-digit major and two-digit minor (e.g. '06.01' or '06-01')"

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "locarno_classes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                f"Locarno classification codes ({_LOCARNO_PATTERN_HINT}). "
                "Filters designs to those carrying any of the given codes."
            ),
        },
        "holder": {
            "type": "string",
            "description": (
                "Optional holder/applicant name substring "
                "(case-insensitive partial match)."
            ),
        },
        "status": {
            "type": "string",
            "description": (
                "Optional EUIPO design status filter "
                "(e.g. 'REGISTERED', 'EXPIRED')."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 10,
            "maximum": 50,
            "description": (
                "Maximum number of results to return (default 20). "
                "EUIPO Design API requires page_size >= 10."
            ),
        },
    },
    "additionalProperties": False,
    "required": [],
}


def _validate_locarno(codes: list[str]) -> list[str]:
    """Accept '06.01' or '06-01' on input, always emit '06.01' (the
    canonical format EUIPO's design endpoint expects)."""
    cleaned: list[str] = []
    for index, code in enumerate(codes):
        if not isinstance(code, str):
            raise ToolError(
                f"locarno_classes[{index}] must be a string ({_LOCARNO_PATTERN_HINT})"
            )
        candidate = code.strip().replace("-", ".")
        if "." not in candidate or len(candidate) > 7:
            raise ToolError(
                f"locarno_classes[{index}]='{code}' is not in the "
                f"{_LOCARNO_PATTERN_HINT} format"
            )
        major, _, minor = candidate.partition(".")
        if not (major.isdigit() and minor.isdigit() and len(major) == 2 and len(minor) == 2):
            raise ToolError(
                f"locarno_classes[{index}]='{code}' must be two digits, a "
                "separator, and two digits (e.g. '06.01')"
            )
        cleaned.append(candidate)
    return cleaned


def _build_rsql(
    *,
    locarno_classes: list[str] | None,
    holder: str | None,
    status: str | None,
) -> str | None:
    parts: list[str] = []
    if locarno_classes:
        joined = ",".join(f"locarnoClasses=={c}" for c in locarno_classes)
        parts.append(f"({joined})")
    if holder:
        escaped = holder.strip().replace('"', '\\"')
        parts.append(f"holders.name==*{escaped}*")
    if status:
        parts.append(f"status=={status.strip()}")
    return " and ".join(parts) if parts else None


def _trim_design(item: dict[str, Any]) -> dict[str, Any]:
    holders = item.get("holders") or []
    holder_names = [
        h.get("name")
        for h in holders
        if isinstance(h, dict) and h.get("name")
    ]
    locarno = item.get("locarnoClasses") or item.get("locarno") or []
    return {
        "design_number": item.get("designNumber") or item.get("identifier"),
        "status": item.get("status"),
        "indication_of_product": item.get("indicationOfProduct")
        or item.get("productIndication"),
        "locarno_classes": locarno,
        "holders": holder_names,
        "filing_date": item.get("filingDate") or item.get("applicationDate"),
        "registration_date": item.get("registrationDate"),
    }


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    locarno_raw = args.get("locarno_classes")
    locarno: list[str] | None = None
    if locarno_raw is not None:
        if not isinstance(locarno_raw, list) or not locarno_raw:
            raise ToolError(
                "locarno_classes must be a non-empty array when provided"
            )
        locarno = _validate_locarno(locarno_raw)

    holder = args.get("holder")
    if holder is not None and (not isinstance(holder, str) or not holder.strip()):
        raise ToolError("holder must be a non-empty string when provided")

    status = args.get("status")
    if status is not None and (not isinstance(status, str) or not status.strip()):
        raise ToolError("status must be a non-empty string when provided")

    limit = args.get("limit") or 20
    if not isinstance(limit, int) or limit < 10 or limit > 50:
        raise ToolError(
            "limit must be an integer between 10 and 50 "
            "(EUIPO Design API requires page_size >= 10)"
        )

    rsql = _build_rsql(
        locarno_classes=locarno,
        holder=holder,
        status=status,
    )

    if rsql is None:
        raise ToolError(
            "design_search needs at least one of locarno_classes, holder, "
            "or status to narrow the query."
        )

    try:
        raw = await search_designs(
            query=rsql,
            page=0,
            page_size=limit,
        )
    except EUIPOClientError as exc:
        raise ToolError(f"EUIPO design search failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"EUIPO design search crashed: {exc}") from exc

    items = raw.get("designs") or raw.get("content") or []
    trimmed = [_trim_design(item) for item in items if isinstance(item, dict)]
    total = raw.get("totalElements") or raw.get("total") or len(trimmed)

    return {
        "filters": {
            "locarno_classes": locarno,
            "holder": holder,
            "status": status,
            "rsql": rsql,
        },
        "total": total,
        "results": trimmed,
    }


design_search_tool = register(
    Tool(
        name="design_search",
        description=(
            "Search the EUIPO Design database for prior registrations "
            "filtered by Locarno class, holder name, and/or status. "
            "Use BEFORE recommending a design filing so the user can "
            "see existing registrations that might block their design."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

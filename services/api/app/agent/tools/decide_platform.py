"""decide_platform tool — country list → IP filing platform mapping.

Reads from data/countries_parsed.json (the same dataset the legacy
EtornieGPT relies on). No hardcoded country lists in code: every lookup
goes through the data file, so adding Turkey, etc. tomorrow is a data
change, not a code change.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.agent.tools.base import Tool, ToolError, register

_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "countries_parsed.json"
)

_lock = Lock()
_by_code: dict[str, dict[str, Any]] = {}
_by_name: dict[str, dict[str, Any]] = {}


def _load_dataset() -> None:
    with _lock:
        if _by_code:
            return
        if not _DATA_PATH.is_file():
            raise ToolError(
                f"Country dataset not found at {_DATA_PATH}. "
                "Cannot resolve platforms without source data."
            )
        rows = json.loads(_DATA_PATH.read_text())
        for row in rows:
            code = (row.get("country_code") or "").strip().upper()
            name = (row.get("country") or "").strip().lower()
            if code:
                _by_code[code] = row
            if name:
                _by_name[name] = row


def _resolve_country(query: str) -> dict[str, Any] | None:
    _load_dataset()
    q = query.strip()
    if not q:
        return None
    upper = q.upper()
    if upper in _by_code:
        return _by_code[upper]
    return _by_name.get(q.lower())


def _yes(value: Any) -> bool:
    return isinstance(value, str) and value.strip().upper() == "YES"


def _platforms_for_country(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered list of viable filing platforms for a single country."""
    code = (row.get("country_code") or "").upper()
    options: list[dict[str, Any]] = []

    # EUIPO covers EU member states via EUTM single application.
    if _yes(row.get("eutm")):
        options.append(
            {
                "platform": "EUIPO",
                "scope": "Single EUTM application covering all EU member states.",
            }
        )

    # USPTO is the federal office for the US.
    if code == "US":
        options.append(
            {"platform": "USPTO", "scope": "United States federal trademark office."}
        )

    # UKIPO is the office for Great Britain (post-Brexit GB office).
    if code == "GB":
        options.append(
            {"platform": "UKIPO", "scope": "United Kingdom Intellectual Property Office."}
        )

    # WIPO Madrid Protocol (only meaningful when designating from a member state;
    # the tool does not enforce origin — the agent will explain to the user).
    if _yes(row.get("madrid")):
        options.append(
            {
                "platform": "WIPO",
                "scope": "International registration via the Madrid Protocol.",
            }
        )

    # National-only path is acknowledged but not wired in Phase 0.
    if not options and _yes(row.get("national")):
        options.append(
            {
                "platform": "NATIONAL_OFFICE",
                "scope": (
                    "Direct national filing required; this country has no "
                    "EUTM, USPTO/UKIPO, or Madrid coverage."
                ),
            }
        )

    return options


_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "countries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "Country names (e.g. 'Germany') or ISO 3166-1 alpha-2 codes "
                "(e.g. 'DE') where trademark protection is sought."
            ),
        }
    },
    "additionalProperties": False,
    "required": ["countries"],
}


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    countries: list[str] = args["countries"]
    if not countries:
        raise ToolError("At least one country must be supplied.")

    per_country: list[dict[str, Any]] = []
    unknown: list[str] = []
    platform_to_countries: dict[str, list[str]] = {}

    for q in countries:
        row = _resolve_country(q)
        if row is None:
            unknown.append(q)
            per_country.append(
                {
                    "input": q,
                    "matched": None,
                    "options": [],
                    "note": (
                        "Country not present in the IP dataset. A national "
                        "filing route is likely required; the orchestrator "
                        "does not yet wire this jurisdiction."
                    ),
                }
            )
            continue

        options = _platforms_for_country(row)
        per_country.append(
            {
                "input": q,
                "matched": {
                    "country": row.get("country"),
                    "country_code": row.get("country_code"),
                },
                "options": options,
            }
        )
        for opt in options:
            platform_to_countries.setdefault(opt["platform"], []).append(
                row.get("country", q)
            )

    # Order platforms by how many of the requested countries they cover —
    # the model can use this to suggest the smallest filing portfolio.
    suggested_route = sorted(
        platform_to_countries.items(),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )

    return {
        "per_country": per_country,
        "platform_coverage": [
            {"platform": p, "covers": cs} for p, cs in suggested_route
        ],
        "unknown_countries": unknown,
    }


decide_platform_tool = register(
    Tool(
        name="decide_platform",
        description=(
            "Given a list of target countries, return the viable IP filing "
            "platforms for each one (EUIPO, USPTO, UKIPO, WIPO, or "
            "NATIONAL_OFFICE) and an aggregate coverage summary. Reads "
            "from the project's country dataset; unknown countries are "
            "reported, not guessed."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

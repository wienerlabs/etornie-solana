"""quote_fees tool — official fee calculation per platform.

EUIPO is wired against the official fee schedule (data/euipo_fees.json,
sourced from euipo.europa.eu and refreshed manually). Other platforms
return ToolError until their adapters land.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.agent.tools.base import Tool, ToolError, register

_EUIPO_FEES_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "euipo_fees.json"
)

_lock = Lock()
_euipo_fees: dict[str, Any] = {}


def _load_euipo_fees() -> dict[str, Any]:
    with _lock:
        if _euipo_fees:
            return _euipo_fees
        if not _EUIPO_FEES_PATH.is_file():
            raise ToolError(
                f"EUIPO fee schedule not found at {_EUIPO_FEES_PATH}. "
                "Cannot quote without source data."
            )
        _euipo_fees.update(json.loads(_EUIPO_FEES_PATH.read_text()))
        return _euipo_fees


def _quote_euipo_trademark(nice_classes: list[int]) -> dict[str, Any]:
    fees = _load_euipo_fees()
    schedule = fees["trademark"]["individual_application"]
    # The LLM occasionally hands Nice class numbers as strings; coerce
    # the *caller-supplied* list to ints so sorted() and < / > checks
    # do not blow up on mixed-type lists. No defaults — empty input
    # raises ToolError below.
    coerced: list[int] = []
    for c in nice_classes or []:
        try:
            coerced.append(int(c))
        except (TypeError, ValueError):
            raise ToolError(
                f"Nice class entries must be integers (1-45). Got: {c!r}"
            )
    sorted_classes = sorted(set(coerced))
    if not sorted_classes:
        raise ToolError("nice_classes must contain at least one class.")
    if any(c < 1 or c > 45 for c in sorted_classes):
        raise ToolError(
            f"Nice classes must be between 1 and 45 (got {sorted_classes})."
        )

    breakdown: list[dict[str, Any]] = []
    total = 0

    breakdown.append(
        {
            "item": f"First class (Nice {sorted_classes[0]})",
            "amount": schedule["first_class"],
        }
    )
    total += schedule["first_class"]

    if len(sorted_classes) >= 2:
        breakdown.append(
            {
                "item": f"Second class (Nice {sorted_classes[1]})",
                "amount": schedule["second_class"],
            }
        )
        total += schedule["second_class"]

    if len(sorted_classes) >= 3:
        extra = sorted_classes[2:]
        per = schedule["additional_class_each"]
        breakdown.append(
            {
                "item": (
                    f"Additional classes ({len(extra)} × Nice "
                    f"{', '.join(str(c) for c in extra)})"
                ),
                "amount": per * len(extra),
            }
        )
        total += per * len(extra)

    return {
        "platform": "EUIPO",
        "currency": fees["currency"],
        "total": total,
        "breakdown": breakdown,
        "source": fees["source"],
        "schedule_last_verified": fees["last_verified"],
    }


_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "platform": {
            "type": "string",
            "enum": ["EUIPO", "WIPO", "USPTO", "UKIPO"],
            "description": "Target IP filing platform.",
        },
        "nice_classes": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 1,
            "description": "Nice classification numbers (1-45).",
        },
    },
    "additionalProperties": False,
    "required": ["platform", "nice_classes"],
}


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    platform = args["platform"]
    nice_classes = list(args["nice_classes"])

    if platform == "EUIPO":
        return _quote_euipo_trademark(nice_classes)

    raise ToolError(
        f"Fee quoting for {platform} is not yet wired. Only EUIPO is "
        "supported in the current milestone; the user should be told that "
        "quotes for other offices will arrive once their adapters land."
    )


quote_fees_tool = register(
    Tool(
        name="quote_fees",
        description=(
            "Calculate the official application fee for a given platform "
            "and Nice class list. EUIPO uses the published fee schedule "
            "from data/euipo_fees.json (sourced from euipo.europa.eu). "
            "Other platforms return an explicit not-wired error."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)

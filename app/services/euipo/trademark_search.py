"""EUIPO Trademark Search API service.

Searches for similar/identical trademarks before filing.
Uses RSQL query language for advanced filtering.
Auth: client_credentials (scope: uid).
Rate limit: 25,000 calls/day.
"""

from typing import Any

from app.services.euipo.client import euipo_request

_RATE_GROUP = "trademark_search"
_BASE_PATH = "/trademark-search"


async def search_trademarks(
    *,
    query: str | None = None,
    mark_text: str | None = None,
    nice_classes: list[int] | None = None,
    offices: list[str] | None = None,
    status: str | None = None,
    fields: list[str] | None = None,
    page: int = 0,
    page_size: int = 20,
    sort: str | None = None,
) -> dict[str, Any]:
    """Search for trademarks using RSQL query or convenience params.

    Args:
        query: Raw RSQL query string (takes precedence).
        mark_text: Trademark name to search (builds RSQL if no raw query).
        nice_classes: Filter by Nice class numbers.
        offices: Filter by office codes (e.g. ["EM", "DE"]).
        status: Filter by status ("REGISTERED", "FILED", "EXPIRED", etc.).
        fields: Specific fields to return in response.
        page: Result page (0-based).
        page_size: Results per page (max 100).
        sort: Sort expression (e.g. "applicationDate:desc").

    Returns:
        Search results with trademark matches.
    """
    # Build RSQL query from convenience params if not provided
    if not query:
        parts = []
        if mark_text:
            escaped = mark_text.replace("'", "\\'")
            parts.append(f"wordMarkSpecification.verbalElement==*{escaped}*")
        if nice_classes:
            cls_str = ",".join(str(c) for c in nice_classes)
            parts.append(f"niceClasses=all=({cls_str})")
        if status:
            parts.append(f"status=={status}")
        query = " and ".join(parts) if parts else None

    params: dict[str, Any] = {
        "page": page,
        "size": min(page_size, 100),
    }
    if query:
        params["query"] = query
    if fields:
        params["fields"] = ",".join(fields)
    if sort:
        params["sort"] = sort

    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/trademarks",
        rate_group=_RATE_GROUP,
        params=params,
    )


async def get_trademark_details(application_number: str) -> dict[str, Any]:
    """Get detailed information about a specific trademark.

    Args:
        application_number: The EUIPO application number.

    Returns:
        Full trademark details.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/trademarks/{application_number}",
        rate_group=_RATE_GROUP,
    )


async def get_trademark_image(
    application_number: str,
    *,
    thumbnail: bool = False,
) -> dict[str, Any]:
    """Get the trademark image/representation.

    Args:
        application_number: The EUIPO application number.
        thumbnail: If True, return thumbnail version.

    Returns:
        Image data/URL.
    """
    path_suffix = "/thumbnail" if thumbnail else ""
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/trademarks/{application_number}/image{path_suffix}",
        rate_group=_RATE_GROUP,
    )

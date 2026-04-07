"""EUIPO Design Search API service.

Searches for similar/identical designs before filing.
Uses RSQL query language for advanced filtering.
Auth: client_credentials (scope: uid).
Rate limit: 35,000 calls/day.
"""

from typing import Any

from app.services.euipo.client import euipo_request

_RATE_GROUP = "design_search"
_BASE_PATH = "/design-search"


async def search_designs(
    *,
    query: str | None = None,
    locarno_classes: list[str] | None = None,
    holder: str | None = None,
    status: str | None = None,
    fields: list[str] | None = None,
    page: int = 0,
    page_size: int = 20,
    sort: str | None = None,
) -> dict[str, Any]:
    """Search for registered designs using RSQL.

    Args:
        query: Raw RSQL query string.
        locarno_classes: Filter by Locarno classification (e.g. ["06-01"]).
        holder: Filter by design holder name.
        status: Filter by status.
        fields: Specific fields to return.
        page: Page number (0-based).
        page_size: Results per page (max 100).
        sort: Sort expression.

    Returns:
        Search results with design matches.
    """
    # Build RSQL if not provided
    if not query:
        parts = []
        if holder:
            parts.append(f"holders.name==*{holder}*")
        if status:
            parts.append(f"status=={status}")
        query = " and ".join(parts) if parts else None

    params: dict[str, Any] = {"page": page, "size": min(page_size, 100)}
    if query:
        params["query"] = query
    if fields:
        params["fields"] = ",".join(fields)
    if sort:
        params["sort"] = sort

    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/designs",
        rate_group=_RATE_GROUP,
        params=params,
    )


async def get_design_details(design_number: str) -> dict[str, Any]:
    """Get detailed information about a specific design.

    Args:
        design_number: The EUIPO design number.

    Returns:
        Full design details.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/designs/{design_number}",
        rate_group=_RATE_GROUP,
    )


async def get_design_view(
    design_number: str,
    view_order: int,
    *,
    thumbnail: bool = False,
) -> dict[str, Any]:
    """Get a design view image.

    Args:
        design_number: The EUIPO design number.
        view_order: View order number.
        thumbnail: If True, return thumbnail version.

    Returns:
        Image data/URL.
    """
    path_suffix = "/thumbnail" if thumbnail else ""
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/designs/{design_number}/views/{view_order}{path_suffix}",
        rate_group=_RATE_GROUP,
    )

"""EUIPO Me (Portfolio) API service.

Manages the user's trademark and design portfolio.
Auth: authorization_code (scopes: me.portfolio.read, me.applicants.read, me.account.read).
Rate limit: 1,000 calls/hour.
"""

from typing import Any

from app.services.euipo.client import euipo_request

_RATE_GROUP = "me"
_BASE_PATH = "/me"


async def get_trademarks(
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 0,
    page_size: int = 20,
    sort: str | None = None,
) -> dict[str, Any]:
    """Get the user's trademark portfolio.

    Args:
        keyword: Search keyword.
        status: Filter by status.
        page: Page number (0-based).
        page_size: Results per page.
        sort: Sort expression.

    Returns:
        Paginated trademark portfolio entries.
    """
    params: dict[str, Any] = {"page": page, "size": min(page_size, 100)}
    if keyword:
        params["keyword"] = keyword
    if status:
        params["status"] = status
    if sort:
        params["sort"] = sort

    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/trademarks",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params=params,
    )


async def get_designs(
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 0,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get the user's design portfolio.

    Args:
        keyword: Search keyword.
        status: Filter by status.
        page: Page number (0-based).
        page_size: Results per page.

    Returns:
        Paginated design portfolio entries.
    """
    params: dict[str, Any] = {"page": page, "size": min(page_size, 100)}
    if keyword:
        params["keyword"] = keyword
    if status:
        params["status"] = status

    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/designs",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params=params,
    )


async def get_oppositions(
    *,
    page: int = 0,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get the user's oppositions."""
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/oppositions",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params={"page": page, "size": min(page_size, 100)},
    )


async def get_applicants(
    *,
    page: int = 0,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get represented applicants."""
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/applicants",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params={"page": page, "size": min(page_size, 100)},
    )


async def get_account() -> dict[str, Any]:
    """Get current EUIPO account information."""
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/account",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def get_account_movements(
    *,
    page: int = 0,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get account financial movements."""
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/account/movements",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params={"page": page, "size": min(page_size, 100)},
    )

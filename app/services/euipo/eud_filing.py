"""EUIPO EUD (EU Design) Filing API service.

Handles design application submission to EUIPO.
Auth: authorization_code (scopes: design-filing.application.read/write).
Rate limit: 1,000 calls/hour.
"""

from typing import Any

from app.services.euipo.client import euipo_request

_RATE_GROUP = "eud_filing"
_BASE_PATH = "/design-filing"


async def create_design_application(
    *,
    designs: list[dict[str, Any]],
    applicant: dict[str, Any],
    representative: dict[str, Any] | None = None,
    locarno_classes: list[str] | None = None,
    language: str = "en",
    deferment: bool = False,
    priority_claim: dict[str, Any] | None = None,
    signatures: list[dict[str, Any]] | None = None,
    payment_method: str = "BANK_TRANSFER",
    validation_only: bool = False,
) -> dict[str, Any]:
    """Create a new EU Design application.

    Args:
        designs: List of design representations with product indications.
        applicant: Applicant details.
        representative: Optional representative/attorney.
        locarno_classes: Locarno classification codes.
        language: Language of the application.
        deferment: Request publication deferment (up to 30 months).
        priority_claim: Optional priority claim.
        signatures: Signatures list.
        payment_method: Payment method.
        validation_only: If True, validate without creating.

    Returns:
        Created application with EUIPO reference.
    """
    body: dict[str, Any] = {
        "designs": designs,
        "applicants": [applicant],
        "language": language,
        "deferment": deferment,
        "paymentPreferences": {"paymentMethod": payment_method},
    }
    if representative:
        body["representatives"] = [representative]
    if locarno_classes:
        body["locarnoClasses"] = locarno_classes
    if priority_claim:
        body["priorities"] = [priority_claim]
    if signatures:
        body["signatures"] = signatures

    extra_headers = {}
    if validation_only:
        extra_headers["Application-Validation-Only"] = "true"

    return await euipo_request(
        "POST",
        f"{_BASE_PATH}/applications",
        rate_group=_RATE_GROUP,
        user_flow=True,
        json_body=body,
        extra_headers=extra_headers or None,
    )


async def get_design_application(application_id: str) -> dict[str, Any]:
    """Get details of an EU Design application.

    Args:
        application_id: EUIPO application identifier.

    Returns:
        Application details and current status.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/applications/{application_id}/receipt",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def get_designers(name: str) -> dict[str, Any]:
    """Search for designers by name.

    Args:
        name: Designer name to search.

    Returns:
        Matching designers.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/designers",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params={"name": name},
    )


async def get_exhibitions(name: str | None = None) -> dict[str, Any]:
    """Search for exhibitions (for exhibition priority claims).

    Args:
        name: Exhibition name to search.

    Returns:
        Matching exhibitions.
    """
    params: dict[str, Any] = {}
    if name:
        params["name"] = name

    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/exhibitions",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params=params or None,
    )

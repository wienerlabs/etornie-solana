"""EUIPO EUTM (EU Trade Mark) Filing API service.

Handles trademark application submission to EUIPO.
Auth: authorization_code (scopes: eutm-filing.application.read/write).
Rate limit: 1,000 calls/hour.
"""

from typing import Any

from app.services.euipo.client import euipo_request

_RATE_GROUP = "eutm_filing"
_BASE_PATH = "/eutm-filing"


async def create_application(
    *,
    mark_text: str,
    mark_feature: str = "WORD",
    nice_classes: list[dict[str, Any]],
    applicant: dict[str, Any],
    representative: dict[str, Any] | None = None,
    first_language: str = "en",
    second_language: str = "fr",
    priority_claim: dict[str, Any] | None = None,
    signatures: list[dict[str, Any]] | None = None,
    payment_method: str = "BANK_TRANSFER",
    draft: bool = True,
) -> dict[str, Any]:
    """Create a new EUTM application.

    Args:
        mark_text: The trademark text/name.
        mark_feature: Mark type ("WORD", "FIGURATIVE", "SHAPE", "SOUND", etc.).
        nice_classes: List of {"classNumber": int, "language": str, "terms": [str]}.
        applicant: Applicant details (type, personIdentifier or name/address).
        representative: Optional representative/attorney details.
        first_language: First language of the application.
        second_language: Second language (must be: en, fr, de, es, or it).
        priority_claim: Optional priority claim.
        signatures: List of {"signature": str, "capacity": str}.
        payment_method: "BANK_TRANSFER", "CURRENT_ACCOUNT", or "CREDIT_CARD".
        draft: If True, save as draft (no payment). If False, file immediately.

    Returns:
        Created application with EUIPO reference number.
    """
    body: dict[str, Any] = {
        "firstLanguage": first_language,
        "secondLanguage": second_language,
        "representation": {
            "wordPhrase": mark_text,
            "markFeature": mark_feature,
        },
        "goodsAndServices": nice_classes,
        "applicants": [applicant],
        "paymentPreferences": {"paymentMethod": payment_method},
    }
    if representative:
        body["representatives"] = [representative]
    if priority_claim:
        body["priorities"] = [priority_claim]
    if signatures:
        body["signatures"] = signatures

    extra_headers = {}
    if draft:
        extra_headers["Application-Draft"] = "true"

    return await euipo_request(
        "POST",
        f"{_BASE_PATH}/applications",
        rate_group=_RATE_GROUP,
        user_flow=True,
        json_body=body,
        extra_headers=extra_headers or None,
    )


async def validate_application(body: dict[str, Any]) -> dict[str, Any]:
    """Validate an application without creating it.

    Args:
        body: Full application body.

    Returns:
        Validation results with any errors.
    """
    return await euipo_request(
        "POST",
        f"{_BASE_PATH}/applications",
        rate_group=_RATE_GROUP,
        user_flow=True,
        json_body=body,
        extra_headers={"Application-Validation-Only": "true"},
    )


async def get_application(application_id: str) -> dict[str, Any]:
    """Get details of an EUTM application.

    Args:
        application_id: EUIPO application identifier.

    Returns:
        Application details and current status.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/applications/{application_id}",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def delete_draft(application_id: str) -> dict[str, Any]:
    """Delete a draft EUTM application.

    Args:
        application_id: EUIPO application identifier.

    Returns:
        Deletion confirmation.
    """
    return await euipo_request(
        "DELETE",
        f"{_BASE_PATH}/applications/{application_id}",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def submit_application(application_id: str) -> dict[str, Any]:
    """Submit a draft application for processing and payment.

    Args:
        application_id: EUIPO application identifier.

    Returns:
        Submission confirmation with filing date/number.
    """
    return await euipo_request(
        "PUT",
        f"{_BASE_PATH}/applications/{application_id}/submit",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def get_filing_receipt(application_id: str) -> dict[str, Any]:
    """Get the filing receipt for a submitted application.

    Args:
        application_id: EUIPO application identifier.

    Returns:
        Filing receipt details.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/applications/{application_id}/receipt",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def list_applications(
    *,
    status: str | None = None,
    page: int = 0,
    page_size: int = 20,
) -> dict[str, Any]:
    """List EUTM applications for the authenticated user.

    Args:
        status: Filter by status ("DRAFT", "FILED", "PUBLISHED", etc.).
        page: Page number (0-based).
        page_size: Results per page.

    Returns:
        Paginated list of applications.
    """
    params: dict[str, Any] = {"page": page, "size": min(page_size, 100)}
    if status:
        params["status"] = status

    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/applications",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params=params,
    )

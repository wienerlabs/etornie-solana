"""EUIPO Document Repository API service.

Handles document upload and management for filings.
Auth: authorization_code (scopes: document-repository.documents.read/write).
Rate limit: 1,000 calls/hour.
"""

from typing import Any

from app.services.euipo.client import euipo_request

_RATE_GROUP = "document_repo"
_BASE_PATH = "/document-repository"


async def upload_document(
    *,
    file_content: bytes,
    filename: str,
    content_type: str = "application/pdf",
) -> dict[str, Any]:
    """Upload a document to EUIPO Document Repository.

    The returned document identifier can be used when filing applications.

    Args:
        file_content: Raw file bytes.
        filename: Original filename.
        content_type: MIME type of the file.

    Returns:
        Upload result with document identifier (UUID).
    """
    return await euipo_request(
        "POST",
        f"{_BASE_PATH}/documents",
        rate_group=_RATE_GROUP,
        user_flow=True,
        files={"file": (filename, file_content, content_type)},
    )


async def list_documents(
    *,
    page: int = 0,
    page_size: int = 20,
) -> dict[str, Any]:
    """List all documents in the user's repository.

    Args:
        page: Page number (0-based).
        page_size: Results per page.

    Returns:
        Paginated list of documents with metadata.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/documents",
        rate_group=_RATE_GROUP,
        user_flow=True,
        params={"page": page, "size": min(page_size, 100)},
    )


async def get_document(document_id: str) -> dict[str, Any]:
    """Get metadata for a specific document.

    Args:
        document_id: Document identifier (UUID).

    Returns:
        Document metadata (filename, size, mimeType, properties).
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/documents/{document_id}",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def delete_document(document_id: str) -> dict[str, Any]:
    """Delete a document from the repository.

    Args:
        document_id: Document identifier (UUID).

    Returns:
        Deletion confirmation.
    """
    return await euipo_request(
        "DELETE",
        f"{_BASE_PATH}/documents/{document_id}",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )


async def download_document(document_id: str) -> dict[str, Any]:
    """Get download URL/content for a document.

    Args:
        document_id: Document identifier (UUID).

    Returns:
        Document export data.
    """
    return await euipo_request(
        "GET",
        f"{_BASE_PATH}/documents/{document_id}/export",
        rate_group=_RATE_GROUP,
        user_flow=True,
    )

"""Tests for document review (approve/reject) workflow."""

import io

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.users.models import User
from tests.conftest import auth_headers


@pytest.fixture
async def uploaded_document(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
) -> dict:
    """Upload a document and return its response dict."""
    file = io.BytesIO(b"test content")
    resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("test.pdf", file, "application/pdf")},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_approve_document(
    client: AsyncClient,
    uploaded_document: dict,
    lawyer_user: User,
):
    """Assigned lawyer can approve a document."""
    doc_id = uploaded_document["id"]
    resp = await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "approve"},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["reviewed_by"] == str(lawyer_user.id)
    assert data["reviewed_at"] is not None
    assert data["rejection_reason"] is None


@pytest.mark.asyncio
async def test_reject_document_with_reason(
    client: AsyncClient,
    uploaded_document: dict,
    lawyer_user: User,
):
    """Assigned lawyer can reject a document with a reason."""
    doc_id = uploaded_document["id"]
    resp = await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "reject", "rejection_reason": "Eksik imza"},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["rejection_reason"] == "Eksik imza"


@pytest.mark.asyncio
async def test_reject_without_reason_fails(
    client: AsyncClient,
    uploaded_document: dict,
    lawyer_user: User,
):
    """Rejecting without a reason returns 422."""
    doc_id = uploaded_document["id"]
    resp = await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "reject"},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_can_review(
    client: AsyncClient,
    uploaded_document: dict,
    admin_user: User,
):
    """Admin can approve documents."""
    doc_id = uploaded_document["id"]
    resp = await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "approve"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_client_cannot_review(
    client: AsyncClient,
    uploaded_document: dict,
    client_user: User,
):
    """Client cannot review documents."""
    doc_id = uploaded_document["id"]
    resp = await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "approve"},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unassigned_lawyer_cannot_review(
    client: AsyncClient,
    uploaded_document: dict,
    second_lawyer_user: User,
):
    """A lawyer not assigned to the case cannot review."""
    doc_id = uploaded_document["id"]
    resp = await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "approve"},
        headers=auth_headers(second_lawyer_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_upload_returns_status_field(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
):
    """Uploaded documents have status=uploaded by default."""
    file = io.BytesIO(b"data")
    resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("file.txt", file, "text/plain")},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "uploaded"


@pytest.mark.asyncio
async def test_upload_with_document_type(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
):
    """Upload with document_type sets the field."""
    file = io.BytesIO(b"data")
    resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("vek.pdf", file, "application/pdf")},
        data={"document_type": "Ülkesel Vekaletname"},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 201
    assert resp.json()["document_type"] == "Ülkesel Vekaletname"

"""Tests for message and document cancellation system."""

import io
import uuid as uuid_mod

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLog
from app.cases.models import Case, CaseNote
from app.documents.models import DocumentStatus
from app.users.models import User
from tests.conftest import auth_headers


# --- Note cancellation tests ---


@pytest.mark.asyncio
async def test_cancel_own_note(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
):
    """User can cancel their own note."""
    # Create note
    resp = await client.post(
        f"/cases/{case_fixture.id}/notes",
        json={"content": "Test note to cancel"},
        headers=auth_headers(client_user),
    )
    note_id = resp.json()["id"]

    # Cancel it
    resp = await client.patch(
        f"/cases/{case_fixture.id}/notes/{note_id}/cancel",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_cancelled"] is True
    assert data["cancelled_by"] == str(client_user.id)
    assert data["cancelled_at"] is not None


@pytest.mark.asyncio
async def test_admin_can_cancel_any_note(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
    admin_user: User,
):
    """Admin can cancel any note."""
    resp = await client.post(
        f"/cases/{case_fixture.id}/notes",
        json={"content": "Client note"},
        headers=auth_headers(client_user),
    )
    note_id = resp.json()["id"]

    resp = await client.patch(
        f"/cases/{case_fixture.id}/notes/{note_id}/cancel",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["is_cancelled"] is True


@pytest.mark.asyncio
async def test_other_user_cannot_cancel_note(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
    lawyer_user: User,
):
    """Lawyer (non-author, non-admin) cannot cancel client's note."""
    resp = await client.post(
        f"/cases/{case_fixture.id}/notes",
        json={"content": "Client note"},
        headers=auth_headers(client_user),
    )
    note_id = resp.json()["id"]

    resp = await client.patch(
        f"/cases/{case_fixture.id}/notes/{note_id}/cancel",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_already_cancelled_note(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
):
    """Cannot cancel an already cancelled note."""
    resp = await client.post(
        f"/cases/{case_fixture.id}/notes",
        json={"content": "Note"},
        headers=auth_headers(client_user),
    )
    note_id = resp.json()["id"]

    await client.patch(
        f"/cases/{case_fixture.id}/notes/{note_id}/cancel",
        headers=auth_headers(client_user),
    )

    resp = await client.patch(
        f"/cases/{case_fixture.id}/notes/{note_id}/cancel",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancelled_note_content_preserved_in_db(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
    db_session: AsyncSession,
):
    """Cancelled note still exists in DB with original content."""
    resp = await client.post(
        f"/cases/{case_fixture.id}/notes",
        json={"content": "Secret content"},
        headers=auth_headers(client_user),
    )
    note_id = resp.json()["id"]

    await client.patch(
        f"/cases/{case_fixture.id}/notes/{note_id}/cancel",
        headers=auth_headers(client_user),
    )

    result = await db_session.execute(
        select(CaseNote).where(CaseNote.id == uuid_mod.UUID(note_id))
    )
    note = result.scalar_one()
    assert note.is_cancelled is True
    assert note.content == "Secret content"  # preserved in DB


# --- Document cancellation tests ---


@pytest.mark.asyncio
async def test_cancel_own_document(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
):
    """Uploader can cancel their own document."""
    file = io.BytesIO(b"test content")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("test.pdf", file, "application/pdf")},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    resp = await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    assert data["cancelled_by"] == str(lawyer_user.id)
    assert data["cancelled_at"] is not None


@pytest.mark.asyncio
async def test_admin_can_cancel_any_document(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
    admin_user: User,
):
    """Admin can cancel any document."""
    file = io.BytesIO(b"data")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("doc.pdf", file, "application/pdf")},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    resp = await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_other_user_cannot_cancel_document(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
    client_user: User,
):
    """Non-uploader, non-admin cannot cancel a document."""
    file = io.BytesIO(b"data")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("doc.pdf", file, "application/pdf")},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    resp = await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_already_cancelled_document(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
):
    """Cannot cancel an already cancelled document."""
    file = io.BytesIO(b"data")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("doc.pdf", file, "application/pdf")},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(lawyer_user),
    )

    resp = await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancelled_document_cannot_be_downloaded(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
):
    """Cancelled document cannot be downloaded."""
    file = io.BytesIO(b"data")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("doc.pdf", file, "application/pdf")},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(lawyer_user),
    )

    resp = await client.get(
        f"/documents/{doc_id}/download",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancel_document_resets_requirement(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
    db_session: AsyncSession,
):
    """Cancelling a document linked to a requirement resets requirement to pending."""
    from app.required_documents.service import (
        create_template,
        generate_case_required_documents,
        list_case_required_documents,
    )

    await create_template(db_session, jurisdiction="Switzerland", document_name="Test Evrak")
    await generate_case_required_documents(
        db_session, case_id=case_fixture.id, jurisdiction="Switzerland", case_type="trademark"
    )

    # Upload with document_type
    file = io.BytesIO(b"content")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("vek.pdf", file, "application/pdf")},
        data={"document_type": "Test Evrak"},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    # Requirement should be uploaded
    reqs = await list_case_required_documents(db_session, case_fixture.id)
    assert reqs[0].status == DocumentStatus.uploaded

    # Cancel the document
    await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(lawyer_user),
    )

    # Check via API endpoint instead of direct DB (avoids session cache)
    resp = await client.get(
        f"/cases/{case_fixture.id}/required-documents",
        headers=auth_headers(lawyer_user),
    )
    req_data = resp.json()["required_documents"][0]
    assert req_data["status"] == "pending"
    assert req_data["document_id"] is None


# --- Audit log tests ---


@pytest.mark.asyncio
async def test_note_cancellation_creates_audit_log(
    client: AsyncClient,
    case_fixture: Case,
    client_user: User,
    db_session: AsyncSession,
):
    """Cancelling a note creates an audit log entry."""
    resp = await client.post(
        f"/cases/{case_fixture.id}/notes",
        json={"content": "Audit test note"},
        headers=auth_headers(client_user),
    )
    note_id = resp.json()["id"]

    await client.patch(
        f"/cases/{case_fixture.id}/notes/{note_id}/cancel",
        headers=auth_headers(client_user),
    )

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.target_id == uuid_mod.UUID(note_id),
            AuditLog.action == AuditAction.note_cancelled,
        )
    )
    log = result.scalar_one()
    assert log.actor_id == client_user.id
    assert log.target_type == "case_note"
    assert log.case_id == case_fixture.id


@pytest.mark.asyncio
async def test_document_cancellation_creates_audit_log(
    client: AsyncClient,
    case_fixture: Case,
    lawyer_user: User,
    db_session: AsyncSession,
):
    """Cancelling a document creates an audit log entry."""
    file = io.BytesIO(b"data")
    upload_resp = await client.post(
        f"/cases/{case_fixture.id}/documents",
        files={"file": ("audit.pdf", file, "application/pdf")},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    await client.patch(
        f"/documents/{doc_id}/cancel",
        headers=auth_headers(lawyer_user),
    )

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.target_id == uuid_mod.UUID(doc_id),
            AuditLog.action == AuditAction.document_cancelled,
        )
    )
    log = result.scalar_one()
    assert log.actor_id == lawyer_user.id
    assert log.target_type == "document"
    assert log.case_id == case_fixture.id
    assert "audit.pdf" in log.details

"""Tests for required documents: templates, case requirements, auto-generation."""

import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.documents.models import DocumentStatus
from app.required_documents.models import CaseRequiredDocument, RequiredDocumentTemplate
from app.required_documents.service import (
    create_template,
    generate_case_required_documents,
    link_document_to_requirement,
    list_case_required_documents,
    regenerate_on_jurisdiction_change,
)
from app.users.models import User
from tests.conftest import auth_headers


@pytest.fixture
async def de_template(db_session: AsyncSession) -> RequiredDocumentTemplate:
    """Create a template for Germany (DE) trademark."""
    return await create_template(
        db_session,
        jurisdiction="DE",
        document_name="Ülkesel Vekaletname",
        description="Almanya için vekaletname",
    )


@pytest.fixture
async def us_template(db_session: AsyncSession) -> RequiredDocumentTemplate:
    """Create a template for USA (US) trademark."""
    return await create_template(
        db_session,
        jurisdiction="US",
        document_name="US Power of Attorney",
        description="ABD için vekaletname",
    )


@pytest.fixture
async def de_case(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> Case:
    """Create a case with DE jurisdiction (without auto-generate, for manual testing)."""
    from app.cases.models import Case, CaseType, CaseStatus

    case = Case(
        case_number="ETR-2026-9999",
        title="DE Test Case",
        case_type=CaseType.trademark,
        status=CaseStatus.open,
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id,
        jurisdiction="DE",
    )
    db_session.add(case)
    await db_session.flush()
    await db_session.refresh(case)
    return case


# --- Template CRUD Tests ---


@pytest.mark.asyncio
async def test_create_template_admin(
    client: AsyncClient,
    admin_user: User,
):
    """Admin can create a template."""
    resp = await client.post(
        "/required-documents/templates",
        json={
            "jurisdiction": "FR",
            "document_name": "Test Evrak",
            "description": "Fransa test",
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["jurisdiction"] == "FR"
    assert data["document_name"] == "Test Evrak"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_template_lawyer_forbidden(
    client: AsyncClient,
    lawyer_user: User,
):
    """Lawyer cannot create templates."""
    resp = await client.post(
        "/required-documents/templates",
        json={"jurisdiction": "FR", "document_name": "Test"},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_templates(
    client: AsyncClient,
    admin_user: User,
    de_template: RequiredDocumentTemplate,
):
    """List templates, optionally filtered."""
    resp = await client.get(
        "/required-documents/templates?jurisdiction=DE",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["templates"][0]["jurisdiction"] == "DE"


# --- Case Required Documents Generation ---


@pytest.mark.asyncio
async def test_generate_case_required_docs(
    db_session: AsyncSession,
    de_template: RequiredDocumentTemplate,
    de_case: Case,
):
    """Generate required documents for a case from templates."""
    created = await generate_case_required_documents(
        db_session,
        case_id=de_case.id,
        jurisdiction="DE",
        case_type="trademark",
    )
    assert len(created) == 1
    assert created[0].document_name == "Ülkesel Vekaletname"
    assert created[0].status == DocumentStatus.pending


@pytest.mark.asyncio
async def test_generate_does_not_duplicate(
    db_session: AsyncSession,
    de_template: RequiredDocumentTemplate,
    de_case: Case,
):
    """Generating twice does not create duplicates."""
    await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )
    second = await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )
    assert len(second) == 0


@pytest.mark.asyncio
async def test_generate_endpoint(
    client: AsyncClient,
    de_template: RequiredDocumentTemplate,
    de_case: Case,
    lawyer_user: User,
):
    """POST /cases/{id}/required-documents/generate works."""
    resp = await client.post(
        f"/cases/{de_case.id}/required-documents/generate",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_list_case_required_docs(
    client: AsyncClient,
    de_template: RequiredDocumentTemplate,
    de_case: Case,
    db_session: AsyncSession,
    lawyer_user: User,
):
    """GET /cases/{id}/required-documents returns all requirements."""
    await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )

    resp = await client.get(
        f"/cases/{de_case.id}/required-documents",
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["required_documents"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_client_can_see_required_docs(
    client: AsyncClient,
    de_template: RequiredDocumentTemplate,
    de_case: Case,
    db_session: AsyncSession,
    client_user: User,
):
    """Client can view required documents for their case."""
    await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )

    resp = await client.get(
        f"/cases/{de_case.id}/required-documents",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# --- Link Document to Requirement ---


@pytest.mark.asyncio
async def test_upload_links_to_requirement(
    client: AsyncClient,
    de_template: RequiredDocumentTemplate,
    de_case: Case,
    db_session: AsyncSession,
    lawyer_user: User,
):
    """Uploading with document_type auto-links to a pending requirement."""
    await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )

    file = io.BytesIO(b"vekaletname data")
    resp = await client.post(
        f"/cases/{de_case.id}/documents",
        files={"file": ("vek.pdf", file, "application/pdf")},
        data={"document_type": "Ülkesel Vekaletname"},
        headers=auth_headers(lawyer_user),
    )
    assert resp.status_code == 201

    # Check that the requirement is now uploaded
    reqs = await list_case_required_documents(db_session, de_case.id)
    assert len(reqs) == 1
    assert reqs[0].status == DocumentStatus.uploaded
    assert reqs[0].document_id is not None


# --- Jurisdiction Change ---


@pytest.mark.asyncio
async def test_jurisdiction_change_removes_pending_only(
    db_session: AsyncSession,
    de_template: RequiredDocumentTemplate,
    us_template: RequiredDocumentTemplate,
    de_case: Case,
):
    """Changing jurisdiction removes pending reqs but preserves uploaded/approved."""
    # Generate DE requirements
    created = await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )
    assert len(created) == 1

    # Simulate: mark one as uploaded (user uploaded the doc)
    created[0].status = DocumentStatus.uploaded
    created[0].document_id = uuid.uuid4()
    await db_session.flush()

    # Now change jurisdiction to US
    new_reqs = await regenerate_on_jurisdiction_change(
        db_session,
        case_id=de_case.id,
        new_jurisdiction="US",
        case_type="trademark",
    )

    all_reqs = await list_case_required_documents(db_session, de_case.id)

    # The DE uploaded one should still be there, plus the new US pending one
    assert len(all_reqs) == 2
    statuses = {r.status for r in all_reqs}
    assert DocumentStatus.uploaded in statuses
    assert DocumentStatus.pending in statuses


@pytest.mark.asyncio
async def test_jurisdiction_change_removes_pending(
    db_session: AsyncSession,
    de_template: RequiredDocumentTemplate,
    us_template: RequiredDocumentTemplate,
    de_case: Case,
):
    """Changing jurisdiction removes pending reqs and adds new ones."""
    await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )

    # Change to US (the DE pending req should be deleted)
    new_reqs = await regenerate_on_jurisdiction_change(
        db_session,
        case_id=de_case.id,
        new_jurisdiction="US",
        case_type="trademark",
    )

    all_reqs = await list_case_required_documents(db_session, de_case.id)
    assert len(all_reqs) == 1
    assert all_reqs[0].document_name == "US Power of Attorney"
    assert all_reqs[0].status == DocumentStatus.pending


# --- Review syncs to CaseRequiredDocument ---


@pytest.mark.asyncio
async def test_review_syncs_to_case_requirement(
    client: AsyncClient,
    de_template: RequiredDocumentTemplate,
    de_case: Case,
    db_session: AsyncSession,
    lawyer_user: User,
):
    """Approving a document syncs status to the linked case requirement."""
    await generate_case_required_documents(
        db_session, case_id=de_case.id, jurisdiction="DE", case_type="trademark"
    )

    # Upload with document_type
    file = io.BytesIO(b"content")
    upload_resp = await client.post(
        f"/cases/{de_case.id}/documents",
        files={"file": ("vek.pdf", file, "application/pdf")},
        data={"document_type": "Ülkesel Vekaletname"},
        headers=auth_headers(lawyer_user),
    )
    doc_id = upload_resp.json()["id"]

    # Approve
    review_resp = await client.patch(
        f"/documents/{doc_id}/review",
        json={"action": "approve"},
        headers=auth_headers(lawyer_user),
    )
    assert review_resp.status_code == 200

    # Check case requirement
    reqs = await list_case_required_documents(db_session, de_case.id)
    assert len(reqs) == 1
    assert reqs[0].status == DocumentStatus.approved

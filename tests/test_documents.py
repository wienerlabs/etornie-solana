import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.config import settings
from app.users.models import User
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def use_tmp_upload_dir(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect upload_dir to a temporary directory for each test."""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


class TestUploadDocument:
    """Tests for POST /cases/{case_id}/documents."""

    async def test_upload_document(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.post(
            f"/cases/{case_fixture.id}/documents",
            headers=headers,
            files={"file": ("test.pdf", b"PDF file content", "application/pdf")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["filename"] == "test.pdf"
        assert data["file_type"] == "application/pdf"
        assert data["file_size"] == len(b"PDF file content")
        assert data["case_id"] == str(case_fixture.id)
        assert data["uploaded_by"] == str(lawyer_user.id)

    async def test_upload_document_unauthorized(
        self,
        client: AsyncClient,
        second_lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(second_lawyer_user)
        response = await client.post(
            f"/cases/{case_fixture.id}/documents",
            headers=headers,
            files={"file": ("test.pdf", b"content", "application/pdf")},
        )
        assert response.status_code == 403


class TestListDocuments:
    """Tests for GET /cases/{case_id}/documents."""

    async def test_list_documents(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        # Upload a document first
        await client.post(
            f"/cases/{case_fixture.id}/documents",
            headers=headers,
            files={"file": ("doc.pdf", b"content", "application/pdf")},
        )

        response = await client.get(
            f"/cases/{case_fixture.id}/documents",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert data["documents"][0]["filename"] == "doc.pdf"


class TestDownloadDocument:
    """Tests for GET /documents/{document_id}/download."""

    async def test_download_document(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        # Upload first
        upload_resp = await client.post(
            f"/cases/{case_fixture.id}/documents",
            headers=headers,
            files={"file": ("download_me.txt", b"hello world", "text/plain")},
        )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["id"]

        # Download
        download_resp = await client.get(
            f"/documents/{doc_id}/download",
            headers=headers,
        )
        assert download_resp.status_code == 200
        assert download_resp.content == b"hello world"

    async def test_download_document_unauthorized(
        self,
        client: AsyncClient,
        lawyer_user: User,
        second_lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        upload_resp = await client.post(
            f"/cases/{case_fixture.id}/documents",
            headers=headers,
            files={"file": ("secret.pdf", b"secret", "application/pdf")},
        )
        doc_id = upload_resp.json()["id"]

        # Unrelated lawyer tries to download
        headers2 = auth_headers(second_lawyer_user)
        response = await client.get(
            f"/documents/{doc_id}/download",
            headers=headers2,
        )
        assert response.status_code == 403


class TestDeleteDocument:
    """Tests for DELETE /documents/{document_id}."""

    async def _upload(
        self,
        client: AsyncClient,
        case_id: str,
        headers: dict[str, str],
    ) -> str:
        """Helper to upload a file and return the document id."""
        resp = await client.post(
            f"/cases/{case_id}/documents",
            headers=headers,
            files={"file": ("to_delete.pdf", b"data", "application/pdf")},
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    async def test_uploader_can_delete(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        doc_id = await self._upload(client, str(case_fixture.id), headers)

        response = await client.delete(
            f"/documents/{doc_id}", headers=headers
        )
        assert response.status_code == 204

    async def test_admin_can_delete(
        self,
        client: AsyncClient,
        admin_user: User,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        # Lawyer uploads
        lawyer_headers = auth_headers(lawyer_user)
        doc_id = await self._upload(client, str(case_fixture.id), lawyer_headers)

        # Admin deletes
        admin_headers = auth_headers(admin_user)
        response = await client.delete(
            f"/documents/{doc_id}", headers=admin_headers
        )
        assert response.status_code == 204

    async def test_non_uploader_non_admin_cannot_delete(
        self,
        client: AsyncClient,
        client_user: User,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        # Lawyer uploads
        lawyer_headers = auth_headers(lawyer_user)
        doc_id = await self._upload(client, str(case_fixture.id), lawyer_headers)

        # Client (who is on the case, but not the uploader) tries to delete
        client_headers = auth_headers(client_user)
        response = await client.delete(
            f"/documents/{doc_id}", headers=client_headers
        )
        assert response.status_code == 403

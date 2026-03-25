import re

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.users.models import User
from tests.conftest import auth_headers


class TestCreateCase:
    """Tests for POST /cases."""

    async def test_admin_creates_case(
        self,
        client: AsyncClient,
        admin_user: User,
        client_user: User,
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Trademark Registration",
                "description": "Register a new trademark",
                "case_type": "trademark",
                "client_id": str(client_user.id),
                "jurisdiction": "Switzerland",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Trademark Registration"
        assert data["case_type"] == "trademark"
        assert data["status"] == "open"
        assert data["client_id"] == str(client_user.id)

    async def test_lawyer_creates_case(
        self,
        client: AsyncClient,
        lawyer_user: User,
        client_user: User,
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Patent Filing",
                "case_type": "patent",
                "client_id": str(client_user.id),
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Patent Filing"
        assert data["case_type"] == "patent"

    async def test_client_cannot_create_case(
        self,
        client: AsyncClient,
        client_user: User,
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Unauthorized Case",
                "case_type": "trademark",
                "client_id": str(client_user.id),
            },
        )
        assert response.status_code == 403

    async def test_case_number_auto_generation(
        self,
        client: AsyncClient,
        admin_user: User,
        client_user: User,
    ) -> None:
        headers = auth_headers(admin_user)

        resp1 = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Case One",
                "case_type": "trademark",
                "client_id": str(client_user.id),
            },
        )
        assert resp1.status_code == 201
        case_number_1 = resp1.json()["case_number"]
        assert re.match(r"ETR-\d{4}-\d{4}", case_number_1)

        resp2 = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Case Two",
                "case_type": "patent",
                "client_id": str(client_user.id),
            },
        )
        assert resp2.status_code == 201
        case_number_2 = resp2.json()["case_number"]
        assert re.match(r"ETR-\d{4}-\d{4}", case_number_2)
        # Second case should have a higher sequence number
        assert case_number_2 > case_number_1


class TestListCases:
    """Tests for GET /cases."""

    async def test_admin_lists_all_cases(
        self,
        client: AsyncClient,
        admin_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.get("/cases", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["cases"]) >= 1

    async def test_lawyer_lists_only_assigned_cases(
        self,
        client: AsyncClient,
        lawyer_user: User,
        second_lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        # Assigned lawyer should see the case
        headers = auth_headers(lawyer_user)
        response = await client.get("/cases", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["cases"][0]["id"] == str(case_fixture.id)

        # Unassigned lawyer should see no cases
        headers2 = auth_headers(second_lawyer_user)
        response2 = await client.get("/cases", headers=headers2)
        assert response2.status_code == 200
        assert response2.json()["total"] == 0

    async def test_client_lists_only_own_cases(
        self,
        client: AsyncClient,
        client_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.get("/cases", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["cases"][0]["client_id"] == str(client_user.id)


class TestGetCase:
    """Tests for GET /cases/{case_id}."""

    async def test_authorized_user_gets_case(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.get(
            f"/cases/{case_fixture.id}", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(case_fixture.id)
        assert data["title"] == "Test IP Case"

    async def test_unauthorized_user_gets_403(
        self,
        client: AsyncClient,
        second_lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(second_lawyer_user)
        response = await client.get(
            f"/cases/{case_fixture.id}", headers=headers
        )
        assert response.status_code == 403


class TestUpdateCase:
    """Tests for PATCH /cases/{case_id}."""

    async def test_admin_can_update_any_case(
        self,
        client: AsyncClient,
        admin_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.patch(
            f"/cases/{case_fixture.id}",
            headers=headers,
            json={"title": "Updated Title", "status": "in_progress"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["status"] == "in_progress"

    async def test_assigned_lawyer_can_update(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.patch(
            f"/cases/{case_fixture.id}",
            headers=headers,
            json={"description": "Updated description"},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "Updated description"

    async def test_non_assigned_lawyer_cannot_update(
        self,
        client: AsyncClient,
        second_lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(second_lawyer_user)
        response = await client.patch(
            f"/cases/{case_fixture.id}",
            headers=headers,
            json={"title": "Hacked"},
        )
        assert response.status_code == 403


class TestCaseNotes:
    """Tests for POST/GET/DELETE /cases/{case_id}/notes."""

    async def test_create_note_authorized(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.post(
            f"/cases/{case_fixture.id}/notes",
            headers=headers,
            json={"content": "Filed initial documents."},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["content"] == "Filed initial documents."
        assert data["case_id"] == str(case_fixture.id)
        assert data["author_id"] == str(lawyer_user.id)

    async def test_list_notes_authorized(
        self,
        client: AsyncClient,
        client_user: User,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        # First create a note
        headers_lawyer = auth_headers(lawyer_user)
        await client.post(
            f"/cases/{case_fixture.id}/notes",
            headers=headers_lawyer,
            json={"content": "Note from lawyer"},
        )

        # Client should be able to read notes
        headers_client = auth_headers(client_user)
        response = await client.get(
            f"/cases/{case_fixture.id}/notes",
            headers=headers_client,
        )
        assert response.status_code == 200
        notes = response.json()
        assert len(notes) >= 1
        assert notes[0]["content"] == "Note from lawyer"

    async def test_admin_can_delete_note(
        self,
        client: AsyncClient,
        admin_user: User,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        # Create a note as lawyer
        headers_lawyer = auth_headers(lawyer_user)
        create_resp = await client.post(
            f"/cases/{case_fixture.id}/notes",
            headers=headers_lawyer,
            json={"content": "Note to delete"},
        )
        note_id = create_resp.json()["id"]

        # Admin deletes it
        headers_admin = auth_headers(admin_user)
        response = await client.delete(
            f"/cases/{case_fixture.id}/notes/{note_id}",
            headers=headers_admin,
        )
        assert response.status_code == 204

        # Verify note is gone
        notes_resp = await client.get(
            f"/cases/{case_fixture.id}/notes",
            headers=headers_admin,
        )
        note_ids = [n["id"] for n in notes_resp.json()]
        assert note_id not in note_ids

    async def test_author_can_delete_own_note(
        self,
        client: AsyncClient,
        lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        headers = auth_headers(lawyer_user)
        create_resp = await client.post(
            f"/cases/{case_fixture.id}/notes",
            headers=headers,
            json={"content": "My own note"},
        )
        note_id = create_resp.json()["id"]

        response = await client.delete(
            f"/cases/{case_fixture.id}/notes/{note_id}",
            headers=headers,
        )
        assert response.status_code == 204

    async def test_unauthorized_user_cannot_delete_note(
        self,
        client: AsyncClient,
        lawyer_user: User,
        second_lawyer_user: User,
        case_fixture: Case,
    ) -> None:
        # Create a note as the assigned lawyer
        headers_lawyer = auth_headers(lawyer_user)
        create_resp = await client.post(
            f"/cases/{case_fixture.id}/notes",
            headers=headers_lawyer,
            json={"content": "Protected note"},
        )
        note_id = create_resp.json()["id"]

        # Second lawyer (not assigned, not author) tries to delete
        headers_second = auth_headers(second_lawyer_user)
        response = await client.delete(
            f"/cases/{case_fixture.id}/notes/{note_id}",
            headers=headers_second,
        )
        assert response.status_code == 403

    async def test_delete_nonexistent_note_returns_404(
        self,
        client: AsyncClient,
        admin_user: User,
        case_fixture: Case,
    ) -> None:
        import uuid as _uuid

        headers = auth_headers(admin_user)
        fake_id = str(_uuid.uuid4())
        response = await client.delete(
            f"/cases/{case_fixture.id}/notes/{fake_id}",
            headers=headers,
        )
        assert response.status_code == 404

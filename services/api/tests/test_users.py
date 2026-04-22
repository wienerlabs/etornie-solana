import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User, UserRole
from tests.conftest import auth_headers


class TestListUsers:
    """Tests for GET /users."""

    async def test_admin_can_list_users(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.get("/users", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "total" in data
        assert data["total"] >= 2

    async def test_lawyer_cannot_list_users(
        self, client: AsyncClient, lawyer_user: User
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.get("/users", headers=headers)
        assert response.status_code == 403

    async def test_client_cannot_list_users(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.get("/users", headers=headers)
        assert response.status_code == 403


class TestGetUser:
    """Tests for GET /users/{id}."""

    async def test_admin_can_get_any_user(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.get(
            f"/users/{client_user.id}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["email"] == "client@etornie.ch"

    async def test_user_can_get_own_profile(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.get(
            f"/users/{client_user.id}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(client_user.id)

    async def test_user_cannot_get_other_profile(
        self, client: AsyncClient, client_user: User, lawyer_user: User
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.get(
            f"/users/{lawyer_user.id}", headers=headers
        )
        assert response.status_code == 403

    async def test_get_nonexistent_user_returns_404(
        self, client: AsyncClient, admin_user: User
    ) -> None:
        headers = auth_headers(admin_user)
        fake_id = uuid.uuid4()
        response = await client.get(f"/users/{fake_id}", headers=headers)
        assert response.status_code == 404


class TestUpdateUser:
    """Tests for PATCH /users/{id}."""

    async def test_admin_can_update_any_user(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.patch(
            f"/users/{client_user.id}",
            headers=headers,
            json={"full_name": "Updated Name"},
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "Updated Name"

    async def test_user_can_update_own_name(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.patch(
            f"/users/{client_user.id}",
            headers=headers,
            json={"full_name": "My New Name"},
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "My New Name"

    async def test_user_cannot_update_other(
        self, client: AsyncClient, client_user: User, lawyer_user: User
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.patch(
            f"/users/{lawyer_user.id}",
            headers=headers,
            json={"full_name": "Hacked"},
        )
        assert response.status_code == 403

    async def test_non_admin_cannot_change_role(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.patch(
            f"/users/{client_user.id}",
            headers=headers,
            json={"role": "admin"},
        )
        assert response.status_code == 403
        assert "Only admins can change user roles" in response.json()["detail"]

    async def test_admin_can_change_role(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.patch(
            f"/users/{client_user.id}",
            headers=headers,
            json={"role": "lawyer"},
        )
        assert response.status_code == 200
        assert response.json()["role"] == "lawyer"


class TestDeleteUser:
    """Tests for DELETE /users/{id}."""

    async def test_admin_can_soft_delete_user(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        headers = auth_headers(admin_user)
        response = await client.delete(
            f"/users/{client_user.id}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    async def test_non_admin_cannot_delete_user(
        self, client: AsyncClient, lawyer_user: User, client_user: User
    ) -> None:
        headers = auth_headers(lawyer_user)
        response = await client.delete(
            f"/users/{client_user.id}", headers=headers
        )
        assert response.status_code == 403

    async def test_delete_nonexistent_user_returns_404(
        self, client: AsyncClient, admin_user: User
    ) -> None:
        headers = auth_headers(admin_user)
        fake_id = uuid.uuid4()
        response = await client.delete(f"/users/{fake_id}", headers=headers)
        assert response.status_code == 404

    async def test_soft_deleted_user_cannot_login(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        """After soft delete, the user should not be able to log in."""
        headers = auth_headers(admin_user)
        await client.delete(f"/users/{client_user.id}", headers=headers)

        login_resp = await client.post(
            "/auth/login",
            json={
                "email": "client@etornie.ch",
                "password": "ClientPass123!",
            },
        )
        assert login_resp.status_code == 401

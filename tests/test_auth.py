import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User
from tests.conftest import auth_headers


class TestRegister:
    """Tests for POST /auth/register."""

    async def test_register_client_success(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "newclient@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "New Client",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newclient@etornie.ch"
        assert data["full_name"] == "New Client"
        assert data["role"] == "client"
        assert data["is_active"] is True
        assert "id" in data

    async def test_register_duplicate_email(self, client: AsyncClient) -> None:
        payload = {
            "email": "dup@etornie.ch",
            "password": "SecurePass123!",
            "full_name": "First User",
        }
        resp1 = await client.post("/auth/register", json=payload)
        assert resp1.status_code == 201

        resp2 = await client.post("/auth/register", json=payload)
        assert resp2.status_code == 409
        assert "already registered" in resp2.json()["detail"]

    async def test_register_invalid_email(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "password": "SecurePass123!",
                "full_name": "Bad Email",
            },
        )
        assert response.status_code == 422

    async def test_register_short_password(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "short@etornie.ch",
                "password": "short",
                "full_name": "Short Pass",
            },
        )
        assert response.status_code == 422

    async def test_register_non_client_role_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "lawyer@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Wannabe Lawyer",
                "role": "lawyer",
            },
        )
        assert response.status_code == 403


class TestLogin:
    """Tests for POST /auth/login."""

    async def test_login_success(
        self, client: AsyncClient, client_user: User
    ) -> None:
        response = await client.post(
            "/auth/login",
            json={
                "email": "client@etornie.ch",
                "password": "ClientPass123!",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(
        self, client: AsyncClient, client_user: User
    ) -> None:
        response = await client.post(
            "/auth/login",
            json={
                "email": "client@etornie.ch",
                "password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    async def test_login_nonexistent_user(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/login",
            json={
                "email": "nobody@etornie.ch",
                "password": "NoUser123!",
            },
        )
        assert response.status_code == 401


class TestMe:
    """Tests for GET /auth/me."""

    async def test_me_with_valid_token(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)
        response = await client.get("/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "client@etornie.ch"
        assert data["role"] == "client"

    async def test_me_without_token(self, client: AsyncClient) -> None:
        response = await client.get("/auth/me")
        assert response.status_code in (401, 403)

    async def test_me_with_malformed_token(self, client: AsyncClient) -> None:
        response = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401


class TestRefresh:
    """Tests for POST /auth/refresh."""

    async def test_refresh_token_flow(
        self, client: AsyncClient, client_user: User
    ) -> None:
        # Login first to get tokens
        login_resp = await client.post(
            "/auth/login",
            json={
                "email": "client@etornie.ch",
                "password": "ClientPass123!",
            },
        )
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]

        # Use refresh token to get new tokens
        refresh_resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 200
        data = refresh_resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_with_invalid_token(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": "invalid.token.value"},
        )
        assert response.status_code == 401

    async def test_refresh_with_access_token_rejected(
        self, client: AsyncClient, client_user: User
    ) -> None:
        """Using an access token as a refresh token should fail."""
        from app.auth.utils import create_access_token

        access_token = create_access_token(str(client_user.id), client_user.role.value)
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": access_token},
        )
        assert response.status_code == 401
        assert "Invalid token type" in response.json()["detail"]

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.email_verification import _pending_verifications
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

    async def test_register_lawyer_role_success(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "lawyer@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "New Lawyer",
                "role": "lawyer",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "lawyer@etornie.ch"
        assert data["role"] == "lawyer"

    async def test_register_admin_role_success(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "newadmin@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "New Admin",
                "role": "admin",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newadmin@etornie.ch"
        assert data["role"] == "admin"


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


class TestEmailVerification:
    """Tests for POST /auth/register/request and POST /auth/register/verify."""

    @pytest.fixture(autouse=True)
    def _clear_pending(self) -> None:
        """Clear pending verifications between tests."""
        _pending_verifications.clear()
        yield
        _pending_verifications.clear()

    @patch("app.auth.email_verification.httpx.AsyncClient")
    async def test_register_request_sends_code(
        self, mock_client_cls: AsyncMock, client: AsyncClient
    ) -> None:
        """Mock EmailJS HTTP call, verify 200 response."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_http_instance = AsyncMock()
        mock_http_instance.post.return_value = mock_response
        mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
        mock_http_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http_instance

        response = await client.post(
            "/auth/register/request",
            json={
                "email": "verify@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Test User",
                "phone": "+905551234567",
                "role": "client",
            },
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Verification code sent to your email"
        mock_http_instance.post.assert_called_once()

    @patch("app.auth.email_verification.httpx.AsyncClient")
    async def test_register_request_duplicate_email(
        self, mock_client_cls: AsyncMock, client: AsyncClient
    ) -> None:
        """Existing email returns 409."""
        # First, create a user via direct register
        await client.post(
            "/auth/register",
            json={
                "email": "existing@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Existing User",
            },
        )

        # Try register/request with same email
        response = await client.post(
            "/auth/register/request",
            json={
                "email": "existing@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Duplicate User",
            },
        )
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]

    @patch("app.auth.email_verification.httpx.AsyncClient")
    async def test_register_verify_valid_code(
        self, mock_client_cls: AsyncMock, client: AsyncClient
    ) -> None:
        """Verify with correct code creates user."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_http_instance = AsyncMock()
        mock_http_instance.post.return_value = mock_response
        mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
        mock_http_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http_instance

        # Step 1: Request verification
        await client.post(
            "/auth/register/request",
            json={
                "email": "newuser@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "New User",
                "role": "client",
            },
        )

        # Grab the stored code
        stored_code = _pending_verifications["newuser@etornie.ch"]["code"]

        # Step 2: Verify the code
        response = await client.post(
            "/auth/register/verify",
            json={
                "email": "newuser@etornie.ch",
                "code": stored_code,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@etornie.ch"
        assert data["full_name"] == "New User"
        assert data["role"] == "client"
        assert data["is_active"] is True

    async def test_register_verify_invalid_code(self, client: AsyncClient) -> None:
        """Wrong code returns 400."""
        from app.auth.email_verification import store_pending

        store_pending(
            "badcode@etornie.ch",
            "123456",
            {
                "email": "badcode@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Bad Code User",
                "phone": None,
                "role": "client",
            },
        )

        response = await client.post(
            "/auth/register/verify",
            json={
                "email": "badcode@etornie.ch",
                "code": "999999",
            },
        )
        assert response.status_code == 400
        assert "Invalid or expired" in response.json()["detail"]

    async def test_register_verify_expired_code(self, client: AsyncClient) -> None:
        """Expired code returns 400."""
        # Store a pending verification with already-expired timestamp
        _pending_verifications["expired@etornie.ch"] = {
            "code": "123456",
            "data": {
                "email": "expired@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Expired User",
                "phone": None,
                "role": "client",
            },
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        }

        response = await client.post(
            "/auth/register/verify",
            json={
                "email": "expired@etornie.ch",
                "code": "123456",
            },
        )
        assert response.status_code == 400
        assert "Invalid or expired" in response.json()["detail"]

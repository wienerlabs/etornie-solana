from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User
from tests.conftest import auth_headers


class TestGuestLinking:
    """Tests for auto-linking guest cases to users on registration."""

    async def test_guest_case_linked_on_register_by_email(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        lawyer_user: User,
    ) -> None:
        """Create a guest case with email, register user with same email, verify linking."""
        guest_email = "guestbyemail@etornie.ch"

        # Create a case with guest client info (no client_id)
        headers = auth_headers(lawyer_user)
        create_resp = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Guest Email Case",
                "case_type": "trademark",
                "guest_client_name": "Future Client",
                "guest_client_email": guest_email,
            },
        )
        assert create_resp.status_code == 201
        case_data = create_resp.json()["case"]
        case_id = case_data["id"]
        assert case_data["client_id"] is None

        # Register a new user with the same email
        reg_resp = await client.post(
            "/auth/register",
            json={
                "email": guest_email,
                "password": "SecurePass123!",
                "full_name": "Guest By Email",
            },
        )
        assert reg_resp.status_code == 201
        user_id = reg_resp.json()["id"]

        # Verify the case is now linked to the new user (use admin to bypass access check)
        case_resp = await client.get(
            f"/cases/{case_id}",
            headers=auth_headers(admin_user),
        )
        assert case_resp.status_code == 200
        assert case_resp.json()["client_id"] == user_id

    async def test_guest_case_linked_on_register_by_phone(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        lawyer_user: User,
    ) -> None:
        """Create a guest case with phone, register user with same phone, verify linking."""
        guest_phone = "+41791234567"

        # Create a case with guest client phone (no client_id)
        headers = auth_headers(lawyer_user)
        create_resp = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Guest Phone Case",
                "case_type": "patent",
                "guest_client_name": "Phone Client",
                "guest_client_phone": guest_phone,
            },
        )
        assert create_resp.status_code == 201
        case_data = create_resp.json()["case"]
        case_id = case_data["id"]
        assert case_data["client_id"] is None

        # Register a new user with the same phone
        reg_resp = await client.post(
            "/auth/register",
            json={
                "email": "phoneuser@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Phone User",
                "phone": guest_phone,
            },
        )
        assert reg_resp.status_code == 201
        user_id = reg_resp.json()["id"]

        # Verify the case is now linked (use admin to bypass access check)
        case_resp = await client.get(
            f"/cases/{case_id}",
            headers=auth_headers(admin_user),
        )
        assert case_resp.status_code == 200
        assert case_resp.json()["client_id"] == user_id

    async def test_guest_case_not_linked_when_no_match(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        lawyer_user: User,
    ) -> None:
        """Register user with different email/phone, verify no linking."""
        # Create a guest case
        headers = auth_headers(lawyer_user)
        create_resp = await client.post(
            "/cases",
            headers=headers,
            json={
                "title": "Unmatched Guest Case",
                "case_type": "design",
                "guest_client_name": "Someone Else",
                "guest_client_email": "someone@etornie.ch",
                "guest_client_phone": "+41799999999",
            },
        )
        assert create_resp.status_code == 201
        case_data = create_resp.json()["case"]
        case_id = case_data["id"]
        assert case_data["client_id"] is None

        # Register a user with completely different email/phone
        reg_resp = await client.post(
            "/auth/register",
            json={
                "email": "different@etornie.ch",
                "password": "SecurePass123!",
                "full_name": "Different User",
                "phone": "+41780000000",
            },
        )
        assert reg_resp.status_code == 201

        # Verify the case is still unlinked (use admin to bypass access check)
        case_resp = await client.get(
            f"/cases/{case_id}",
            headers=auth_headers(admin_user),
        )
        assert case_resp.status_code == 200
        assert case_resp.json()["client_id"] is None

    async def test_multiple_guest_cases_linked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        lawyer_user: User,
    ) -> None:
        """Multiple guest cases linked at once when user registers."""
        guest_email = "multi@etornie.ch"
        headers = auth_headers(lawyer_user)

        # Create multiple guest cases with the same email
        case_ids = []
        for i in range(3):
            create_resp = await client.post(
                "/cases",
                headers=headers,
                json={
                    "title": f"Multi Guest Case {i + 1}",
                    "case_type": "copyright",
                    "guest_client_name": "Multi Client",
                    "guest_client_email": guest_email,
                },
            )
            assert create_resp.status_code == 201
            case_data = create_resp.json()["case"]
            assert case_data["client_id"] is None
            case_ids.append(case_data["id"])

        # Register user with matching email
        reg_resp = await client.post(
            "/auth/register",
            json={
                "email": guest_email,
                "password": "SecurePass123!",
                "full_name": "Multi User",
            },
        )
        assert reg_resp.status_code == 201
        user_id = reg_resp.json()["id"]

        # Verify all cases are now linked (use admin to bypass access check)
        for case_id in case_ids:
            case_resp = await client.get(
                f"/cases/{case_id}",
                headers=auth_headers(admin_user),
            )
            assert case_resp.status_code == 200
            assert case_resp.json()["client_id"] == user_id

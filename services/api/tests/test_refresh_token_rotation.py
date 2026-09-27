"""Tests for refresh token rotation + reuse detection (issue #35).

Covers the scenarios the issue calls out explicitly:
- happy-path rotation
- reuse of an already-redeemed token revokes the whole family
- a revoked family cannot refresh again
- two concurrent sessions (families) for the same user stay independent
"""
from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
from app.users.models import User


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200
    return resp.json()


class TestRefreshRotation:
    async def test_happy_path_rotation_returns_new_tokens(
        self, client: AsyncClient, client_user: User
    ) -> None:
        tokens = await _login(client, "client@etornie.ch", "ClientPass123!")
        old_refresh = tokens["refresh_token"]

        resp = await client.post(
            "/auth/refresh", json={"refresh_token": old_refresh}
        )
        assert resp.status_code == 200
        new_tokens = resp.json()
        assert new_tokens["refresh_token"] != old_refresh
        assert "access_token" in new_tokens

    async def test_reused_token_revokes_family_and_returns_401(
        self, client: AsyncClient, client_user: User
    ) -> None:
        tokens = await _login(client, "client@etornie.ch", "ClientPass123!")
        old_refresh = tokens["refresh_token"]

        # First redemption succeeds and rotates.
        first = await client.post(
            "/auth/refresh", json={"refresh_token": old_refresh}
        )
        assert first.status_code == 200
        new_refresh = first.json()["refresh_token"]

        # Replaying the now-consumed old token is theft evidence.
        second = await client.post(
            "/auth/refresh", json={"refresh_token": old_refresh}
        )
        assert second.status_code == 401

        # The whole family — including the token issued by the first,
        # legitimate rotation — must now be revoked too.
        third = await client.post(
            "/auth/refresh", json={"refresh_token": new_refresh}
        )
        assert third.status_code == 401

    async def test_revoked_family_cannot_refresh(
        self, client: AsyncClient, client_user: User
    ) -> None:
        tokens = await _login(client, "client@etornie.ch", "ClientPass123!")
        refresh_token = tokens["refresh_token"]

        logout_resp = await client.post(
            "/auth/logout", json={"refresh_token": refresh_token}
        )
        assert logout_resp.status_code == 204

        refresh_resp = await client.post(
            "/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert refresh_resp.status_code == 401

    async def test_concurrent_sessions_stay_independent(
        self, client: AsyncClient, client_user: User
    ) -> None:
        session_a = await _login(client, "client@etornie.ch", "ClientPass123!")
        session_b = await _login(client, "client@etornie.ch", "ClientPass123!")
        assert session_a["refresh_token"] != session_b["refresh_token"]

        # Rotating session A must not affect session B.
        rotate_a = await client.post(
            "/auth/refresh", json={"refresh_token": session_a["refresh_token"]}
        )
        assert rotate_a.status_code == 200

        rotate_b = await client.post(
            "/auth/refresh", json={"refresh_token": session_b["refresh_token"]}
        )
        assert rotate_b.status_code == 200

    async def test_logout_only_revokes_the_presented_family(
        self, client: AsyncClient, client_user: User
    ) -> None:
        session_a = await _login(client, "client@etornie.ch", "ClientPass123!")
        session_b = await _login(client, "client@etornie.ch", "ClientPass123!")

        logout_resp = await client.post(
            "/auth/logout", json={"refresh_token": session_a["refresh_token"]}
        )
        assert logout_resp.status_code == 204

        # Session A is dead...
        refresh_a = await client.post(
            "/auth/refresh", json={"refresh_token": session_a["refresh_token"]}
        )
        assert refresh_a.status_code == 401

        # ...but session B is untouched.
        refresh_b = await client.post(
            "/auth/refresh", json={"refresh_token": session_b["refresh_token"]}
        )
        assert refresh_b.status_code == 200

    async def test_logout_with_unknown_token_is_a_no_op(
        self, client: AsyncClient
    ) -> None:
        """Logout never errors, even for a token the server has never seen."""
        resp = await client.post(
            "/auth/logout", json={"refresh_token": "not-a-real-token"}
        )
        assert resp.status_code == 204


class TestRefreshTokenPersistence:
    async def test_login_persists_a_hashed_refresh_token_row(
        self,
        client: AsyncClient,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        tokens = await _login(client, "client@etornie.ch", "ClientPass123!")

        rows = (
            await db_session.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == client_user.id
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.token_hash != tokens["refresh_token"]
        assert row.redeemed_at is None
        assert row.revoked_at is None

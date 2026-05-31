"""Profile-picture (avatar) persistence.

Regression guard for "I change my profile picture but it does not save": the
bytes must land in the DB (so the avatar survives a redeploy on ephemeral
hosting) and be served back verbatim.
"""
from httpx import AsyncClient

from app.users.models import User
from tests.conftest import auth_headers

_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes-for-test"


class TestAvatar:
    async def test_upload_persists_to_db_and_serves(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)

        resp = await client.post(
            "/users/me/avatar",
            headers=headers,
            files={"file": ("avatar.png", _PNG, "image/png")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["has_avatar"] is True
        assert body["avatar_mime"] == "image/png"

        got = await client.get(
            f"/users/{client_user.id}/avatar", headers=headers
        )
        assert got.status_code == 200
        assert got.content == _PNG
        assert got.headers["content-type"].startswith("image/png")

    async def test_delete_clears_avatar(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)
        await client.post(
            "/users/me/avatar",
            headers=headers,
            files={"file": ("a.png", _PNG, "image/png")},
        )

        deleted = await client.delete("/users/me/avatar", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["has_avatar"] is False

        got = await client.get(
            f"/users/{client_user.id}/avatar", headers=headers
        )
        assert got.status_code == 404

    async def test_unsupported_mime_rejected(
        self, client: AsyncClient, client_user: User
    ) -> None:
        headers = auth_headers(client_user)
        resp = await client.post(
            "/users/me/avatar",
            headers=headers,
            files={"file": ("bad.txt", b"not an image", "text/plain")},
        )
        assert resp.status_code == 400

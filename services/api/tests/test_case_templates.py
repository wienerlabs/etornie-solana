"""Tests for case templates (issue #65).

Real DB, no mocks: templates are listed through the live endpoint and
cases are created from them through the real create-case pipeline.
"""
import pytest
from httpx import AsyncClient

from app.users.models import User
from tests.conftest import auth_headers


class TestListCaseTemplates:
    async def test_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/case-templates")
        assert resp.status_code == 401

    async def test_lists_templates(
        self, client: AsyncClient, client_user: User
    ) -> None:
        resp = await client.get(
            "/case-templates", headers=auth_headers(client_user)
        )
        assert resp.status_code == 200
        templates = resp.json()["templates"]
        by_key = {t["key"]: t for t in templates}
        assert {
            "trademark-renewal",
            "patent-filing",
            "design-registration",
        } <= set(by_key)
        assert by_key["patent-filing"]["case_type"] == "patent"
        assert by_key["design-registration"]["case_type"] == "design"
        assert by_key["trademark-renewal"]["default_title"] == "Trademark Renewal"


class TestCreateFromTemplate:
    async def test_create_with_template_only(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        # No title / case_type — both come from the template.
        resp = await client.post(
            "/cases",
            json={
                "template_key": "patent-filing",
                "client_id": str(client_user.id),
            },
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 201, resp.text
        case = resp.json()["case"]
        assert case["case_type"] == "patent"
        assert case["title"] == "Patent Filing"

    async def test_request_fields_override_template(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        resp = await client.post(
            "/cases",
            json={
                "template_key": "patent-filing",
                "title": "My Custom Patent",
                "client_id": str(client_user.id),
            },
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 201, resp.text
        case = resp.json()["case"]
        # Title overridden by the request; case_type still from template.
        assert case["title"] == "My Custom Patent"
        assert case["case_type"] == "patent"

    async def test_unknown_template_rejected(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        resp = await client.post(
            "/cases",
            json={
                "template_key": "does-not-exist",
                "client_id": str(client_user.id),
            },
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 400

    async def test_no_template_still_requires_title_and_type(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        # Neither template_key nor title/case_type → schema rejects (422).
        resp = await client.post(
            "/cases",
            json={"client_id": str(client_user.id)},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 422

    async def test_plain_create_without_template_still_works(
        self, client: AsyncClient, admin_user: User, client_user: User
    ) -> None:
        resp = await client.post(
            "/cases",
            json={
                "title": "Manual Case",
                "case_type": "trademark",
                "client_id": str(client_user.id),
            },
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["case"]["title"] == "Manual Case"

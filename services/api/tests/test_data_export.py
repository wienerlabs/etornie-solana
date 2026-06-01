"""Tests for GDPR Article 20 data export (GET /users/me/export).

Exercises the real read path against the in-memory SQLite test DB with
real rows inserted through the ORM — no mocks, no stubs. Verifies the
export is scoped to the authenticated subject, includes related rows
reached through parent tables, and never leaks credentials.
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import AgentMessage, AgentMessageRole, AgentSession
from app.audit.models import AuditAction, AuditLog
from app.cases.service import create_case
from app.etorniegpt.models import ChatMessage
from app.in_app_notifications.models import (
    InAppNotification,
    InAppNotificationType,
)
from app.compliance.data_export_render import render_pdf
from app.users.models import User
from tests.conftest import auth_headers


async def _seed_user_data(db: AsyncSession, user: User) -> dict[str, str]:
    """Insert one real row per representative table owned by ``user``.

    Returns the identifiers the assertions look for so the test does not
    depend on field ordering.
    """
    case = await create_case(
        db,
        title="My Trademark",
        # Special characters (< > &) exercise the PDF renderer's XML
        # escaping — reportlab parses Paragraph text as mini-HTML.
        description="Owned by <subject> & protected in classes 9 > 35",
        case_type="trademark",
        client_id=user.id,
        jurisdiction="Switzerland",
    )

    chat = ChatMessage(
        user_id=user.id,
        question="How long does an EUIPO trademark take?",
        answer="Compare A&B <fast> vs slow > average; depends on oppositions.",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
    )
    db.add(chat)

    session = AgentSession(
        user_id=user.id,
        title="Filing assistant",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
    )
    db.add(session)
    await db.flush()

    message = AgentMessage(
        session_id=session.id,
        role=AgentMessageRole.user,
        content="I want to register a logo.",
    )
    db.add(message)

    notification = InAppNotification(
        recipient_id=user.id,
        notification_type=InAppNotificationType.case_created,
        title="Case created",
        message="Your case My Trademark was created.",
        case_id=case.id,
    )
    db.add(notification)

    audit = AuditLog(
        actor_id=user.id,
        action=AuditAction.note_cancelled,
        target_type="case_note",
        target_id=uuid.uuid4(),
        case_id=case.id,
        details="cancelled a note",
    )
    db.add(audit)

    await db.flush()
    return {
        "case_id": str(case.id),
        "session_id": str(session.id),
        "message_content": message.content,
        "chat_question": chat.question,
    }


class TestDataExportAuth:
    async def test_export_requires_authentication(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/users/me/export")
        assert response.status_code == 401


class TestDataExportShape:
    async def test_export_returns_json_attachment(
        self, client: AsyncClient, client_user: User
    ) -> None:
        response = await client.get(
            "/users/me/export", headers=auth_headers(client_user)
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert f"etornie-data-export-{client_user.id}.json" in disposition

        payload = response.json()
        assert payload["export_format"] == "etornie-gdpr-data-export"
        assert "Article 20" in payload["gdpr_basis"]
        assert payload["generated_at"]
        assert payload["subject"]["user_id"] == str(client_user.id)
        assert payload["subject"]["email"] == client_user.email
        # Empty account: every collection present and empty-shaped.
        assert payload["data"]["cases"] == []
        assert payload["data"]["agent_messages"] == []

    async def test_export_never_leaks_password_hash(
        self, client: AsyncClient, client_user: User
    ) -> None:
        response = await client.get(
            "/users/me/export", headers=auth_headers(client_user)
        )
        assert response.status_code == 200
        profile = response.json()["data"]["profile"]
        assert profile["id"] == str(client_user.id)
        assert "hashed_password" not in profile
        # And it must not leak anywhere else in the document either.
        assert "hashed_password" not in response.text


class TestDataExportContent:
    async def test_export_includes_owned_rows(
        self,
        client: AsyncClient,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        seeded = await _seed_user_data(db_session, client_user)

        response = await client.get(
            "/users/me/export", headers=auth_headers(client_user)
        )
        assert response.status_code == 200
        data = response.json()["data"]

        assert {c["id"] for c in data["cases"]} == {seeded["case_id"]}
        assert data["cases"][0]["title"] == "My Trademark"

        assert {m["question"] for m in data["etorniegpt_chat_messages"]} == {
            seeded["chat_question"]
        }

        # Child row reached only through the subject's agent session.
        assert {s["id"] for s in data["agent_sessions"]} == {
            seeded["session_id"]
        }
        assert {m["content"] for m in data["agent_messages"]} == {
            seeded["message_content"]
        }

        assert len(data["in_app_notifications"]) == 1
        assert data["in_app_notifications"][0]["title"] == "Case created"

        assert len(data["audit_logs"]) == 1
        assert data["audit_logs"][0]["action"] == "note_cancelled"

class TestDataExportFormats:
    async def test_invalid_format_is_rejected(
        self, client: AsyncClient, client_user: User
    ) -> None:
        response = await client.get(
            "/users/me/export",
            params={"format": "csv"},
            headers=auth_headers(client_user),
        )
        assert response.status_code == 422

    async def test_pdf_export(
        self,
        client: AsyncClient,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        await _seed_user_data(db_session, client_user)
        response = await client.get(
            "/users/me/export",
            params={"format": "pdf"},
            headers=auth_headers(client_user),
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert ".pdf" in response.headers["content-disposition"]
        # Valid PDF files start with the %PDF magic header.
        assert response.content[:4] == b"%PDF"

    async def test_docx_export(
        self,
        client: AsyncClient,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        await _seed_user_data(db_session, client_user)
        response = await client.get(
            "/users/me/export",
            params={"format": "docx"},
            headers=auth_headers(client_user),
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
        # DOCX/XLSX are ZIP containers — they start with the PK magic.
        assert response.content[:2] == b"PK"

    async def test_xlsx_export(
        self,
        client: AsyncClient,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        await _seed_user_data(db_session, client_user)
        response = await client.get(
            "/users/me/export",
            params={"format": "xlsx"},
            headers=auth_headers(client_user),
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        )
        assert response.content[:2] == b"PK"

    def test_pdf_renders_record_taller_than_a_page(self) -> None:
        # A single agent-message tool_result can be a JSONB blob taller
        # than a PDF page. Table rows cannot split across pages, so the
        # renderer must flow such records as paragraphs instead.
        huge_value = " ".join(f"token{i}" for i in range(4000))
        export = {
            "export_format": "etornie-gdpr-data-export",
            "export_version": "1",
            "gdpr_basis": "Article 20",
            "generated_at": "2026-06-01T00:00:00+00:00",
            "subject": {
                "user_id": "u1",
                "email": "a@b.com",
                "full_name": "X",
                "wallet_address": None,
                "public_handle": None,
            },
            "data": {
                "profile": {"id": "u1", "full_name": "X"},
                "agent_messages": [
                    {"id": "m1", "tool_result": {"text": huge_value}}
                ],
            },
        }
        pdf = render_pdf(export)
        assert pdf[:4] == b"%PDF"

    async def test_empty_account_renders_every_format(
        self, client: AsyncClient, client_user: User
    ) -> None:
        # No seeded data: renderers must still produce valid files.
        for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK"), ("xlsx", b"PK")):
            response = await client.get(
                "/users/me/export",
                params={"format": fmt},
                headers=auth_headers(client_user),
            )
            assert response.status_code == 200, fmt
            assert response.content[: len(magic)] == magic, fmt


class TestDataExportScope:
    async def test_export_is_scoped_to_subject(
        self,
        client: AsyncClient,
        client_user: User,
        second_lawyer_user: User,
        db_session: AsyncSession,
    ) -> None:
        # client_user owns data; second_lawyer_user (a different client)
        # must not see any of it in their own export.
        seeded = await _seed_user_data(db_session, client_user)

        response = await client.get(
            "/users/me/export", headers=auth_headers(second_lawyer_user)
        )
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["cases"] == []
        assert data["etorniegpt_chat_messages"] == []
        assert data["agent_sessions"] == []
        assert data["agent_messages"] == []
        assert data["in_app_notifications"] == []
        assert data["audit_logs"] == []
        # Sanity: the other user's identifiers appear nowhere.
        assert seeded["case_id"] not in response.text
        assert seeded["session_id"] not in response.text

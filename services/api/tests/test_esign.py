"""Tests for the e-signature lane (issue #63).

No mocks: webhook HMAC verification uses real hashing, the webhook
state-machine runs against real SignatureRequest rows in the test DB
with constructed Yousign-shaped payloads (data fixtures, not behaviour
mocks), and any path that must call Yousign is skipped when
YOUSIGN_API_KEY is absent (skip ≠ mock).
"""
import hashlib
import hmac
import json
import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.esign import service as esign_service
from app.esign import yousign_client
from app.esign.models import (
    SignatureProvider,
    SignatureRequest,
    SignatureRequestStatus,
)
from app.cases.models import Case
from app.documents.models import Document
from app.users.models import User
from tests.conftest import auth_headers

_SECRET = "whsec_test_esign_secret"


@pytest.fixture
def webhook_secret():
    saved = settings.yousign_webhook_secret
    settings.yousign_webhook_secret = _SECRET
    try:
        yield _SECRET
    finally:
        settings.yousign_webhook_secret = saved


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()


async def _make_request_row(
    db: AsyncSession,
    case: Case,
    signer: User,
    *,
    status: SignatureRequestStatus = SignatureRequestStatus.ongoing,
    provider_request_id: str = "sr_test_1",
) -> SignatureRequest:
    row = SignatureRequest(
        case_id=case.id,
        source_document_id=None,
        signer_user_id=signer.id,
        provider=SignatureProvider.yousign,
        status=status,
        provider_request_id=provider_request_id,
        provider_document_id="doc_test_1",
        signer_email=signer.email or "x@example.com",
        signer_name=signer.full_name or "Client",
        subject="Sign this",
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Webhook HMAC verification (pure)
# ---------------------------------------------------------------------------


class TestWebhookVerification:
    def test_valid_signature(self, webhook_secret) -> None:
        body = b'{"event_name":"signature_request.done"}'
        assert yousign_client.verify_webhook(body, _sign(body)) is True

    def test_tampered_body_fails(self, webhook_secret) -> None:
        good = _sign(b'{"a":1}')
        assert yousign_client.verify_webhook(b'{"a":2}', good) is False

    def test_missing_header_fails(self, webhook_secret) -> None:
        assert yousign_client.verify_webhook(b"{}", None) is False

    def test_no_secret_fails_closed(self) -> None:
        saved = settings.yousign_webhook_secret
        settings.yousign_webhook_secret = ""
        try:
            body = b"{}"
            assert yousign_client.verify_webhook(body, _sign(body)) is False
        finally:
            settings.yousign_webhook_secret = saved


class TestNameSplit:
    def test_split_name(self) -> None:
        assert esign_service._split_name("Muhammed Akinci") == (
            "Muhammed",
            "Akinci",
        )
        assert esign_service._split_name("Cher") == ("Cher", "Cher")
        assert esign_service._split_name("") == ("Client", "Client")
        assert esign_service._split_name("A B C") == ("A", "B C")

    def test_split_name_sanitizes_unauthorized_chars(self) -> None:
        # Yousign rejects underscores/digits; an auto-generated wallet
        # handle must be cleaned to letters before being sent.
        assert esign_service._split_name("etornie_CBDjvUkZ") == (
            "etornie",
            "CBDjvUkZ",
        )
        assert esign_service._split_name("wallet_0x1234") == (
            "wallet",
            "x",
        )
        # All-unauthorized collapses to the safe fallback.
        assert esign_service._split_name("___999") == ("Client", "Client")


# ---------------------------------------------------------------------------
# Webhook state-machine (real DB, constructed payloads)
# ---------------------------------------------------------------------------


class TestWebhookStateMachine:
    async def test_declined_updates_row(
        self, db_session: AsyncSession, case_fixture: Case, client_user: User
    ) -> None:
        row = await _make_request_row(db_session, case_fixture, client_user)
        event = {
            "event_name": "signature_request.declined",
            "data": {"signature_request": {"id": row.provider_request_id}},
        }
        result = await esign_service.handle_webhook(db_session, event)
        assert result["handled"] is True
        await db_session.refresh(row)
        assert row.status == SignatureRequestStatus.declined

    async def test_expired_updates_row(
        self, db_session: AsyncSession, case_fixture: Case, client_user: User
    ) -> None:
        row = await _make_request_row(
            db_session, case_fixture, client_user, provider_request_id="sr_exp"
        )
        event = {
            "event_name": "signature_request.expired",
            "data": {"signature_request": {"id": "sr_exp"}},
        }
        await esign_service.handle_webhook(db_session, event)
        await db_session.refresh(row)
        assert row.status == SignatureRequestStatus.expired

    async def test_ignored_event(self, db_session: AsyncSession) -> None:
        result = await esign_service.handle_webhook(
            db_session,
            {"event_name": "signer.notified", "data": {}},
        )
        assert result["handled"] is False
        assert result["reason"] == "ignored_event"

    async def test_unknown_request_ignored(
        self, db_session: AsyncSession
    ) -> None:
        result = await esign_service.handle_webhook(
            db_session,
            {
                "event_name": "signature_request.declined",
                "data": {"signature_request": {"id": "sr_nope"}},
            },
        )
        assert result["handled"] is False
        assert result["reason"] == "request_not_found"

    async def test_already_signed_is_noop(
        self, db_session: AsyncSession, case_fixture: Case, client_user: User
    ) -> None:
        row = await _make_request_row(
            db_session,
            case_fixture,
            client_user,
            status=SignatureRequestStatus.signed,
            provider_request_id="sr_signed",
        )
        result = await esign_service.handle_webhook(
            db_session,
            {
                "event_name": "signature_request.done",
                "data": {"signature_request": {"id": "sr_signed"}},
            },
        )
        # No Yousign download happens because the row is already signed.
        assert result["handled"] is True
        assert result["reason"] == "already_signed"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class TestEsignEndpoints:
    async def test_create_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/esign/signature-requests",
            json={"case_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401

    async def test_list_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/esign/signature-requests",
            params={"case_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401

    async def test_webhook_rejects_bad_signature(
        self, client: AsyncClient, webhook_secret
    ) -> None:
        resp = await client.post(
            "/esign/webhook",
            content=b'{"event_name":"signature_request.done"}',
            headers={"X-Yousign-Signature-256": "sha256=deadbeef"},
        )
        assert resp.status_code == 401

    async def test_webhook_valid_signature_updates_row(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        case_fixture: Case,
        client_user: User,
        webhook_secret,
    ) -> None:
        row = await _make_request_row(
            db_session, case_fixture, client_user, provider_request_id="sr_wh"
        )
        await db_session.commit()
        body = json.dumps(
            {
                "event_name": "signature_request.declined",
                "data": {"signature_request": {"id": "sr_wh"}},
            }
        ).encode()
        resp = await client.post(
            "/esign/webhook",
            content=body,
            headers={"X-Yousign-Signature-256": _sign(body)},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "declined"

    async def test_create_unknown_case_404(
        self, client: AsyncClient, client_user: User
    ) -> None:
        resp = await client.post(
            "/esign/signature-requests",
            json={"case_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4())},
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 404

    async def test_create_forbidden_for_non_owner(
        self,
        client: AsyncClient,
        case_fixture: Case,
        second_lawyer_user: User,
        db_session: AsyncSession,
    ) -> None:
        # case_fixture client is client_user; second_lawyer_user is a
        # different client → no access.
        doc = Document(
            case_id=case_fixture.id,
            uploaded_by=case_fixture.client_id,
            filename="affidavit.pdf",
            file_path="/tmp/does-not-matter.pdf",
            file_type="application/pdf",
            file_size=10,
        )
        db_session.add(doc)
        await db_session.commit()
        resp = await client.post(
            "/esign/signature-requests",
            json={"case_id": str(case_fixture.id), "document_id": str(doc.id)},
            headers=auth_headers(second_lawyer_user),
        )
        assert resp.status_code == 403

    async def test_create_missing_file_404(
        self,
        client: AsyncClient,
        case_fixture: Case,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        # Owner access OK, signer has email, but the file is absent on
        # disk → service refuses before any Yousign call.
        doc = Document(
            case_id=case_fixture.id,
            uploaded_by=client_user.id,
            filename="missing.pdf",
            file_path="/tmp/nonexistent-" + uuid.uuid4().hex + ".pdf",
            file_type="application/pdf",
            file_size=10,
        )
        db_session.add(doc)
        await db_session.commit()
        resp = await client.post(
            "/esign/signature-requests",
            json={"case_id": str(case_fixture.id), "document_id": str(doc.id)},
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 404


@pytest.mark.skipif(
    not settings.yousign_api_key,
    reason="YOUSIGN_API_KEY not configured (live Yousign call)",
)
class TestYousignLive:
    async def test_create_signature_request_live(
        self,
        client: AsyncClient,
        case_fixture: Case,
        client_user: User,
        db_session: AsyncSession,
    ) -> None:
        # Real Yousign sandbox call: upload a real one-page PDF and send.
        pdf = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF"
        )
        case_dir = os.path.join(settings.upload_dir, str(case_fixture.id))
        os.makedirs(case_dir, exist_ok=True)
        path = os.path.join(case_dir, f"{uuid.uuid4()}_affidavit.pdf")
        with open(path, "wb") as fh:
            fh.write(pdf)
        doc = Document(
            case_id=case_fixture.id,
            uploaded_by=client_user.id,
            filename="affidavit.pdf",
            file_path=path,
            file_type="application/pdf",
            file_size=len(pdf),
        )
        db_session.add(doc)
        await db_session.commit()

        resp = await client.post(
            "/esign/signature-requests",
            json={"case_id": str(case_fixture.id), "document_id": str(doc.id)},
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "ongoing"

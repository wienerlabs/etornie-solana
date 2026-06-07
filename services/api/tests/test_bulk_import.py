"""Tests for bulk case import from CSV / XML (issue #67).

Real DB, no mocks: rows are parsed from real CSV/XML bytes and created
through the real create_case pipeline; per-row failures are asserted on
actual report output.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.bulk_import import (
    BulkImportParseError,
    import_cases,
    parse_csv,
    parse_xml,
    parse_upload,
)
from app.cases.models import Case
from app.users.models import User
from tests.conftest import auth_headers


class TestParsing:
    def test_csv_headers_normalised_and_bom_safe(self) -> None:
        content = "﻿title,Case_Type,jurisdiction\nMy Mark,trademark,DE\n"
        rows = parse_csv(content.encode("utf-8"))
        assert rows == [
            {"title": "My Mark", "case_type": "trademark", "jurisdiction": "DE"}
        ]

    def test_csv_drops_empty_and_unknown_columns(self) -> None:
        rows = parse_csv(b"title,case_type,bogus\nA,patent,\n")
        assert rows == [{"title": "A", "case_type": "patent"}]

    def test_xml_child_tags_and_attributes(self) -> None:
        xml = (
            b"<cases>"
            b"<case><title>X</title><case_type>patent</case_type></case>"
            b'<case title="Y" case_type="design"/>'
            b"</cases>"
        )
        rows = parse_xml(xml)
        assert {"title": "X", "case_type": "patent"} in rows
        assert {"title": "Y", "case_type": "design"} in rows

    def test_xml_rejects_xxe(self) -> None:
        # External-entity (XXE) payload must be refused, not resolved.
        xxe = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b"<cases><case><title>&x;</title>"
            b"<case_type>patent</case_type></case></cases>"
        )
        with pytest.raises(BulkImportParseError):
            parse_xml(xxe)

    def test_parse_upload_rejects_unknown_extension(self) -> None:
        with pytest.raises(BulkImportParseError):
            parse_upload("portfolio.txt", b"whatever")

    def test_header_aliases_map_to_canonical(self) -> None:
        # Real-world headers: Mark/Type/Country/Classes/Owner.
        rows = parse_csv(
            b"Mark,Type,Country,Classes,Owner\n"
            b"Acme,Trade Mark,DE,25,Acme GmbH\n"
        )
        assert rows == [
            {
                "title": "Acme",
                "case_type": "Trade Mark",
                "jurisdiction": "DE",
                "nice_classes": "25",
                "client_name": "Acme GmbH",
            }
        ]

    def test_semicolon_with_aliases(self) -> None:
        rows = parse_csv(
            "Trademark Name;Matter Type;Territory\nBrand;TM;FR\n".encode()
        )
        assert rows == [
            {"title": "Brand", "case_type": "TM", "jurisdiction": "FR"}
        ]


class TestImportCases:
    async def test_creates_good_rows_and_reports_bad(
        self, db_session: AsyncSession
    ) -> None:
        rows = parse_csv(
            b"title,case_type,jurisdiction\n"
            b"Alpha Mark,trademark,DE\n"
            b"Beta Patent,patent,EU\n"
            b"Broken,notatype,EU\n"          # invalid case_type
            b",trademark,EU\n"               # missing title
        )
        results = await import_cases(db_session, rows)
        assert [r.status for r in results] == [
            "created",
            "created",
            "failed",
            "failed",
        ]
        assert results[0].case_number
        assert "case_type" in (results[2].error or "")
        assert "title" in (results[3].error or "")

        # The two good cases really exist.
        created_ids = [
            uuid.UUID(r.case_id) for r in results if r.status == "created"
        ]
        found = (
            await db_session.execute(
                select(Case).where(Case.id.in_(created_ids))
            )
        ).scalars().all()
        assert len(found) == 2

    async def test_client_email_links_registered_user(
        self, db_session: AsyncSession, client_user: User
    ) -> None:
        rows = parse_csv(
            (
                "title,case_type,client_email\n"
                f"Linked,trademark,{client_user.email}\n"
                "Guesty,patent,nobody@nowhere.test\n"
            ).encode("utf-8")
        )
        results = await import_cases(db_session, rows)
        assert all(r.status == "created" for r in results)

        linked = (
            await db_session.execute(
                select(Case).where(Case.id == uuid.UUID(results[0].case_id))
            )
        ).scalar_one()
        assert linked.client_id == client_user.id

        guest = (
            await db_session.execute(
                select(Case).where(Case.id == uuid.UUID(results[1].case_id))
            )
        ).scalar_one()
        assert guest.client_id is None
        assert guest.guest_client_email == "nobody@nowhere.test"

    async def test_aliased_headers_and_case_type_values_import(
        self, db_session: AsyncSession
    ) -> None:
        # Headers and case_type values both use real-world variants.
        rows = parse_csv(
            b"Mark,Type,Country\n"
            b"Aliased Mark,Trade Mark,DE\n"
            b"Aliased Pat,pat,EU\n"
        )
        results = await import_cases(db_session, rows)
        assert [r.status for r in results] == ["created", "created"]

    async def test_default_case_type_for_files_without_a_type_column(
        self, db_session: AsyncSession
    ) -> None:
        # A trademark-portfolio export with no type column: default fills.
        rows = parse_csv(b"Mark,Country\nAcme Brand,DE\nBeta Brand,FR\n")
        results = await import_cases(
            db_session, rows, default_case_type="trademark"
        )
        assert [r.status for r in results] == ["created", "created"]

    async def test_no_type_and_no_default_fails(
        self, db_session: AsyncSession
    ) -> None:
        rows = parse_csv(b"Mark,Country\nAcme Brand,DE\n")
        results = await import_cases(db_session, rows)
        assert results[0].status == "failed"
        assert "case_type" in (results[0].error or "")

    async def test_bad_row_does_not_block_following_rows(
        self, db_session: AsyncSession
    ) -> None:
        rows = parse_csv(
            b"title,case_type\nBad,bogus\nGood,design\n"
        )
        results = await import_cases(db_session, rows)
        assert results[0].status == "failed"
        assert results[1].status == "created"


class TestBulkImportEndpoint:
    async def test_requires_admin(
        self, client: AsyncClient, client_user: User
    ) -> None:
        resp = await client.post(
            "/cases/bulk-import",
            files={"file": ("p.csv", b"title,case_type\nA,trademark\n", "text/csv")},
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 403

    async def test_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/cases/bulk-import",
            files={"file": ("p.csv", b"title,case_type\nA,trademark\n", "text/csv")},
        )
        assert resp.status_code == 401

    async def test_csv_import_report(
        self, client: AsyncClient, admin_user: User
    ) -> None:
        csv_bytes = (
            b"title,case_type,jurisdiction\n"
            b"Endpoint Mark,trademark,DE\n"
            b"Nope,invalidtype,EU\n"
        )
        resp = await client.post(
            "/cases/bulk-import",
            files={"file": ("portfolio.csv", csv_bytes, "text/csv")},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        assert body["created"] == 1
        assert body["failed"] == 1

    async def test_empty_file_rejected(
        self, client: AsyncClient, admin_user: User
    ) -> None:
        resp = await client.post(
            "/cases/bulk-import",
            files={"file": ("p.csv", b"", "text/csv")},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 400

    async def test_unsupported_type_rejected(
        self, client: AsyncClient, admin_user: User
    ) -> None:
        resp = await client.post(
            "/cases/bulk-import",
            files={"file": ("p.txt", b"title,case_type\nA,trademark\n", "text/plain")},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 400

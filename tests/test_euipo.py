"""Tests for EUIPO API services.

Uses httpx mock to test services without hitting the real EUIPO API.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.euipo.auth import (
    _client_cache,
    get_client_credentials_token,
    invalidate_token,
)
from app.services.euipo.client import EUIPOClientError, _rate_limiter, euipo_request


# ── Auth Tests ──


class TestOAuth2Auth:
    """Test OAuth2 token management."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        invalidate_token()
        yield
        invalidate_token()

    @pytest.mark.asyncio
    async def test_get_client_credentials_token_fetches_new(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test-token-123",
            "expires_in": 28800,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.euipo.auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            token = await get_client_credentials_token()
            assert token == "test-token-123"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_client_credentials_token_uses_cache(self):
        _client_cache.access_token = "cached-token"
        _client_cache.expires_at = time.time() + 3600

        token = await get_client_credentials_token()
        assert token == "cached-token"

    @pytest.mark.asyncio
    async def test_invalidate_token(self):
        _client_cache.access_token = "old-token"
        _client_cache.expires_at = time.time() + 3600

        invalidate_token()
        assert _client_cache.access_token == ""
        assert _client_cache.expires_at == 0.0


# ── Rate Limiter Tests ──


class TestRateLimiter:
    @pytest.fixture(autouse=True)
    def _reset_limiter(self):
        _rate_limiter._calls.clear()
        yield

    @pytest.mark.asyncio
    async def test_acquire_under_limit(self):
        """Should not block when under the limit."""
        start = time.time()
        await _rate_limiter.acquire("trademark_search")
        elapsed = time.time() - start
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_unknown_group_passes(self):
        """Unknown rate group should not block."""
        await _rate_limiter.acquire("unknown_group")


# ── Client Tests ──


class TestEUIPOClient:
    @pytest.mark.asyncio
    async def test_successful_request(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        with patch("app.services.euipo.client.get_auth_headers", return_value={"Authorization": "Bearer test"}):
            with patch("app.services.euipo.client.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.request.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_cls.return_value = mock_client

                result = await euipo_request(
                    "GET", "/test", rate_group="trademark_search"
                )
                assert result == {"results": []}

    @pytest.mark.asyncio
    async def test_401_triggers_retry(self):
        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_401.text = "Unauthorized"

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"ok": True}

        with patch("app.services.euipo.client.get_auth_headers", return_value={"Authorization": "Bearer test"}):
            with patch("app.services.euipo.client.invalidate_token"):
                with patch("app.services.euipo.client.httpx.AsyncClient") as mock_cls:
                    mock_client = AsyncMock()
                    mock_client.request.side_effect = [mock_401, mock_200]
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_cls.return_value = mock_client

                    result = await euipo_request(
                        "GET", "/test", rate_group="trademark_search"
                    )
                    assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_error_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.side_effect = Exception("not json")

        with patch("app.services.euipo.client.get_auth_headers", return_value={"Authorization": "Bearer test"}):
            with patch("app.services.euipo.client.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.request.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_cls.return_value = mock_client

                with pytest.raises(EUIPOClientError) as exc_info:
                    await euipo_request("GET", "/test", rate_group="me")
                assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_204_returns_empty(self):
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("app.services.euipo.client.get_auth_headers", return_value={"Authorization": "Bearer test"}):
            with patch("app.services.euipo.client.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.request.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_cls.return_value = mock_client

                result = await euipo_request("DELETE", "/test", rate_group="me")
                assert result == {}


# ── Trademark Search Tests ──


class TestTrademarkSearch:
    @pytest.mark.asyncio
    async def test_search_trademarks(self):
        with patch("app.services.euipo.trademark_search.euipo_request") as mock_req:
            mock_req.return_value = {
                "results": [{"markText": "ETORNIE", "status": "REGISTERED"}],
                "total": 1,
            }

            from app.services.euipo.trademark_search import search_trademarks

            result = await search_trademarks(
                mark_text="ETORNIE", nice_classes=[9, 42]
            )
            assert result["total"] == 1
            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args
            assert "ETORNIE" in call_kwargs.kwargs["params"]["query"]
            assert "niceClasses" in call_kwargs.kwargs["params"]["query"]

    @pytest.mark.asyncio
    async def test_get_trademark_details(self):
        with patch("app.services.euipo.trademark_search.euipo_request") as mock_req:
            mock_req.return_value = {"markText": "TEST", "id": "123"}

            from app.services.euipo.trademark_search import get_trademark_details

            result = await get_trademark_details("123")
            assert result["id"] == "123"


# ── Goods & Services Tests ──


class TestGoodsServices:
    @pytest.mark.asyncio
    async def test_search_terms(self):
        with patch("app.services.euipo.goods_services.euipo_request") as mock_req:
            mock_req.return_value = {"terms": [{"term": "software", "niceClass": 9}]}

            from app.services.euipo.goods_services import search_terms

            result = await search_terms(query="software", nice_class=9)
            assert len(result["terms"]) == 1

    @pytest.mark.asyncio
    async def test_validate_classification(self):
        with patch("app.services.euipo.goods_services.euipo_request") as mock_req:
            mock_req.return_value = {"accepted": 1, "rejected": 0}

            from app.services.euipo.goods_services import validate_classification

            result = await validate_classification(
                [{"classNumber": 9, "terms": ["computer software"]}]
            )
            assert result["accepted"] == 1


# ── EUTM Filing Tests ──


class TestEUTMFiling:
    @pytest.mark.asyncio
    async def test_create_application(self):
        with patch("app.services.euipo.eutm_filing.euipo_request") as mock_req:
            mock_req.return_value = {
                "applicationId": "EUTM-2026-001",
                "status": "DRAFT",
            }

            from app.services.euipo.eutm_filing import create_application

            result = await create_application(
                mark_text="ETORNIE",
                nice_classes=[{"classNumber": 42, "terms": "SaaS"}],
                applicant={"name": "Test", "address": "Test Addr", "country": "TR"},
            )
            assert result["applicationId"] == "EUTM-2026-001"

    @pytest.mark.asyncio
    async def test_submit_application(self):
        with patch("app.services.euipo.eutm_filing.euipo_request") as mock_req:
            mock_req.return_value = {"status": "FILED", "filingDate": "2026-04-07"}

            from app.services.euipo.eutm_filing import submit_application

            result = await submit_application("EUTM-2026-001")
            assert result["status"] == "FILED"


# ── Document Repo Tests ──


class TestDocumentRepo:
    @pytest.mark.asyncio
    async def test_upload_document(self):
        with patch("app.services.euipo.document_repo.euipo_request") as mock_req:
            mock_req.return_value = {"identifier": "doc-123"}

            from app.services.euipo.document_repo import upload_document

            result = await upload_document(
                file_content=b"fake-pdf-content",
                filename="power_of_attorney.pdf",
            )
            assert result["identifier"] == "doc-123"

    @pytest.mark.asyncio
    async def test_list_documents(self):
        with patch("app.services.euipo.document_repo.euipo_request") as mock_req:
            mock_req.return_value = {"documents": []}

            from app.services.euipo.document_repo import list_documents

            result = await list_documents()
            assert result["documents"] == []


# ── Portfolio Tests ──


class TestPortfolio:
    @pytest.mark.asyncio
    async def test_get_trademarks(self):
        with patch("app.services.euipo.portfolio.euipo_request") as mock_req:
            mock_req.return_value = {"entries": [], "total": 0}

            from app.services.euipo.portfolio import get_trademarks

            result = await get_trademarks()
            assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_get_account(self):
        with patch("app.services.euipo.portfolio.euipo_request") as mock_req:
            mock_req.return_value = {"name": "Destek Patent", "status": "ACTIVE"}

            from app.services.euipo.portfolio import get_account

            result = await get_account()
            assert result["status"] == "ACTIVE"


# ── Design Search Tests ──


class TestDesignSearch:
    @pytest.mark.asyncio
    async def test_search_designs(self):
        with patch("app.services.euipo.design_search.euipo_request") as mock_req:
            mock_req.return_value = {"results": [], "total": 0}

            from app.services.euipo.design_search import search_designs

            result = await search_designs(query="chair", locarno_classes=["06-01"])
            assert result["total"] == 0


# ── EUD Filing Tests ──


class TestEUDFiling:
    @pytest.mark.asyncio
    async def test_create_design_application(self):
        with patch("app.services.euipo.eud_filing.euipo_request") as mock_req:
            mock_req.return_value = {
                "applicationId": "EUD-2026-001",
                "status": "DRAFT",
            }

            from app.services.euipo.eud_filing import create_design_application

            result = await create_design_application(
                designs=[{"productIndication": "Chair"}],
                applicant={"name": "Test", "address": "Test", "country": "DE"},
                locarno_classes=["06-01"],
            )
            assert result["applicationId"] == "EUD-2026-001"

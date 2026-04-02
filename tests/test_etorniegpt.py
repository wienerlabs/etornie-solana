"""Tests for EtornieGPT: country detection, context building, and API endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from app.etorniegpt.countries import (
    detect_country_from_question,
    find_country,
    format_country_context,
)
from app.etorniegpt.service import _build_messages, SYSTEM_PROMPT
from app.users.models import User
from tests.conftest import auth_headers


# --- Country lookup tests ---


class TestFindCountry:
    def test_find_by_code(self):
        result = find_country("DE")
        assert result is not None
        assert "ALMANYA" in result["ulke"].upper()

    def test_find_by_code_lowercase(self):
        result = find_country("de")
        assert result is not None

    def test_find_by_name_turkish(self):
        result = find_country("Almanya")
        assert result is not None
        assert result["ulke_kodu"] == "DE"

    def test_find_by_alias_english(self):
        result = find_country("Germany")
        assert result is not None
        assert "ALMANYA" in result["ulke"].upper()

    def test_find_by_alias_usa(self):
        result = find_country("USA")
        assert result is not None
        assert result["ulke_kodu"] == "US"

    def test_find_by_alias_abd(self):
        result = find_country("ABD")
        assert result is not None
        assert result["ulke_kodu"] == "US"

    def test_find_by_alias_uk(self):
        result = find_country("UK")
        assert result is not None

    def test_find_nonexistent(self):
        result = find_country("Atlantis")
        assert result is None

    def test_find_empty_string(self):
        result = find_country("")
        assert result is None


class TestDetectCountryFromQuestion:
    def test_detect_almanya(self):
        result = detect_country_from_question("Almanya'da marka tescili ne kadar sürer?")
        assert result is not None
        assert "ALMANYA" in result["ulke"].upper()

    def test_detect_germany_english(self):
        result = detect_country_from_question("How long does trademark registration take in Germany?")
        assert result is not None
        assert "ALMANYA" in result["ulke"].upper()

    def test_detect_usa(self):
        result = detect_country_from_question("ABD'de patent başvurusu nasıl yapılır?")
        assert result is not None
        assert result["ulke_kodu"] == "US"

    def test_detect_japan(self):
        result = detect_country_from_question("Japonya'da marka koruma süresi nedir?")
        assert result is not None

    def test_no_country_in_question(self):
        result = detect_country_from_question("Nice sınıflandırması nedir?")
        assert result is None

    def test_no_country_for_nice_class(self):
        result = detect_country_from_question("Nice Sınıflandırması'nda Sınıf 25 neyi kapsar?")
        assert result is None

    def test_no_country_for_madrid(self):
        result = detect_country_from_question("Madrid sistemi nedir?")
        assert result is None

    def test_no_country_for_aripo(self):
        result = detect_country_from_question("ARIPO nedir?")
        assert result is None

    def test_no_country_for_general_patent(self):
        result = detect_country_from_question("Patent başvurusu nasıl yapılır?")
        assert result is None

    def test_detect_fransa(self):
        result = detect_country_from_question("Fransa'da tescil süreci hakkında bilgi ver")
        assert result is not None
        assert result["ulke_kodu"] == "FR"

    def test_detect_parenthesized_anguilla(self):
        result = detect_country_from_question("Anguilla'da marka tescili nasıl yapılır?")
        assert result is not None
        assert result["ulke_kodu"] == "AI"

    def test_detect_parenthesized_bermuda(self):
        result = detect_country_from_question("Bermuda'da tescil süresi ne kadar?")
        assert result is not None
        assert result["ulke_kodu"] == "BM"

    def test_detect_parenthesized_christmas(self):
        result = detect_country_from_question("Christmas Adası'nda koruma süresi nedir?")
        assert result is not None
        assert result["ulke_kodu"] == "AU"


class TestFormatCountryContext:
    def test_format_has_key_fields(self):
        country = find_country("DE")
        assert country is not None
        context = format_country_context(country)
        assert "Ulke:" in context
        assert "Tescil Suresi:" in context

    def test_format_skips_null_fields(self):
        context = format_country_context({"ulke": "Test", "madrid": None, "zorunlu_evraklar": None})
        assert "Madrid" not in context
        assert "Zorunlu" not in context


# --- Message building tests ---


class TestBuildMessages:
    def test_with_country_data_in_user_message(self):
        """Country data must be in user message, not system prompt."""
        messages, country_name = _build_messages("Almanya'da marka tescili ne kadar sürer?")
        assert country_name is not None
        assert "ALMANYA" in country_name.upper()
        # System prompt stays clean
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == SYSTEM_PROMPT
        # Country data is in user message
        user_msg = messages[1]["content"]
        assert "kesin veriler" in user_msg
        assert "Tescil Suresi:" in user_msg
        assert "SADECE" in user_msg

    def test_without_country(self):
        """General questions get plain user message."""
        messages, country_name = _build_messages("Nice sınıflandırması nedir?")
        assert country_name is None
        assert messages[0]["content"] == SYSTEM_PROMPT
        assert messages[1]["content"] == "Nice sınıflandırması nedir?"

    def test_bahreyn_data_in_user_message(self):
        """Bahreyn data must appear in user message with exact DB values."""
        messages, _ = _build_messages("Bahreyn'de tescil süresi ne kadar?")
        user_msg = messages[1]["content"]
        assert "Tescil Suresi:" in user_msg
        assert "5 - 7 ay" in user_msg  # exact value from DB

    def test_system_prompt_never_has_country_data(self):
        """System prompt must always be the base prompt, never enriched."""
        messages, _ = _build_messages("Fransa'da marka başvurusu nasıl yapılır?")
        assert messages[0]["content"] == SYSTEM_PROMPT


# --- API endpoint tests (LLM mocked) ---


def _mock_together_response(content: str) -> MagicMock:
    """Create a mock Together AI response."""
    choice = MagicMock()
    choice.message.content = content

    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_etorniegpt_endpoint_with_country(
    client: AsyncClient,
    admin_user: User,
):
    """Endpoint returns answer with detected country."""
    mock_resp = _mock_together_response("Almanya'da marka tescili yaklaşık 3 ay sürer.")

    with patch("app.etorniegpt.service.Together") as MockTogether:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        MockTogether.return_value = mock_client

        resp = await client.post(
            "/etorniegpt",
            json={"question": "Almanya'da marka tescili ne kadar sürer?"},
            headers=auth_headers(admin_user),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "Almanya" in data["answer"]
    assert data["country_detected"] is not None
    assert data["model"] == "openai/gpt-oss-20b"


@pytest.mark.asyncio
async def test_etorniegpt_endpoint_without_country(
    client: AsyncClient,
    admin_user: User,
):
    """Endpoint works when no country is detected."""
    mock_resp = _mock_together_response("Nice sınıflandırması, mal ve hizmetlerin sınıflandırılması sistemidir.")

    with patch("app.etorniegpt.service.Together") as MockTogether:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        MockTogether.return_value = mock_client

        resp = await client.post(
            "/etorniegpt",
            json={"question": "Nice sınıflandırması nedir?"},
            headers=auth_headers(admin_user),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["country_detected"] is None


@pytest.mark.asyncio
async def test_etorniegpt_requires_auth(client: AsyncClient):
    """Endpoint requires authentication."""
    resp = await client.post(
        "/etorniegpt",
        json={"question": "Test"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_etorniegpt_empty_question(
    client: AsyncClient,
    admin_user: User,
):
    """Empty question returns 422."""
    resp = await client.post(
        "/etorniegpt",
        json={"question": ""},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_etorniegpt_passes_country_data_in_user_message(
    client: AsyncClient,
    admin_user: User,
):
    """Verify country data is in user message, system prompt stays clean."""
    mock_resp = _mock_together_response("Test answer")

    with patch("app.etorniegpt.service.Together") as MockTogether:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        MockTogether.return_value = mock_client

        await client.post(
            "/etorniegpt",
            json={"question": "Fransa'da marka başvurusu nasıl yapılır?"},
            headers=auth_headers(admin_user),
        )

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        # System prompt is clean
        assert messages[0]["content"] == SYSTEM_PROMPT
        # Country data is in user message
        user_msg = messages[1]["content"]
        assert "kesin veriler" in user_msg
        assert "FRANSA" in user_msg.upper() or "FR" in user_msg


@pytest.mark.asyncio
async def test_etorniegpt_unknown_country_no_llm_call(
    client: AsyncClient,
    admin_user: User,
):
    """Country not in DB returns hardcoded response without calling LLM."""
    with patch("app.etorniegpt.service.Together") as MockTogether:
        resp = await client.post(
            "/etorniegpt",
            json={"question": "Türkiye'de marka tescili nasıl yapılır?"},
            headers=auth_headers(admin_user),
        )

        # LLM should NOT be called
        MockTogether.return_value.chat.completions.create.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert "veritaban" in data["answer"].lower()
    assert data["country_detected"] is None

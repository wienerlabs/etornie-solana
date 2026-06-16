"""Tests for EtornieGPT: country detection, context building, and API endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from app.config import settings
from app.etorniegpt.countries import (
    detect_country_from_question,
    find_country,
    format_country_context,
)
from app.etorniegpt.service import (
    _build_messages,
    _question_mentions_unknown_country,
    SYSTEM_PROMPT,
)
from app.users.models import User
from tests.conftest import auth_headers


# --- Country lookup tests ---


class TestFindCountry:
    def test_find_by_code(self):
        result = find_country("DE")
        assert result is not None
        assert "GERMANY" in result["country"].upper()

    def test_find_by_code_lowercase(self):
        result = find_country("de")
        assert result is not None

    def test_find_by_name_english(self):
        result = find_country("Germany")
        assert result is not None
        assert result["country_code"] == "DE"

    def test_find_by_alias_turkish(self):
        result = find_country("Almanya")
        assert result is not None
        assert "GERMANY" in result["country"].upper()

    def test_find_by_alias_usa(self):
        result = find_country("USA")
        assert result is not None
        assert result["country_code"] == "US"

    def test_find_by_alias_abd(self):
        result = find_country("ABD")
        assert result is not None
        assert result["country_code"] == "US"

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
    def test_detect_germany_turkish(self):
        result = detect_country_from_question("Almanya'da marka tescili ne kadar sürer?")
        assert result is not None
        assert "GERMANY" in result["country"].upper()

    def test_detect_germany_english(self):
        result = detect_country_from_question("How long does trademark registration take in Germany?")
        assert result is not None
        assert "GERMANY" in result["country"].upper()

    def test_detect_usa(self):
        result = detect_country_from_question("How is a patent application filed in the USA?")
        assert result is not None
        assert result["country_code"] == "US"

    def test_detect_japan(self):
        result = detect_country_from_question("What is the trademark protection period in Japan?")
        assert result is not None

    def test_no_country_in_question(self):
        result = detect_country_from_question("What is Nice classification?")
        assert result is None

    def test_no_country_for_nice_class(self):
        result = detect_country_from_question("What does Class 25 cover in Nice Classification?")
        assert result is None

    def test_no_country_for_madrid(self):
        result = detect_country_from_question("What is the Madrid system?")
        assert result is None

    def test_no_country_for_aripo(self):
        result = detect_country_from_question("What is ARIPO?")
        assert result is None

    def test_no_country_for_general_patent(self):
        result = detect_country_from_question("How is a patent application filed?")
        assert result is None

    def test_detect_france(self):
        result = detect_country_from_question("Give me information about the registration process in France")
        assert result is not None
        assert result["country_code"] == "FR"

    def test_detect_parenthesized_anguilla(self):
        result = detect_country_from_question("How is trademark registration done in Anguilla?")
        assert result is not None
        assert result["country_code"] == "AI"

    def test_detect_parenthesized_bermuda(self):
        result = detect_country_from_question("How long is the registration period in Bermuda?")
        assert result is not None
        assert result["country_code"] == "BM"

    def test_detect_parenthesized_christmas(self):
        result = detect_country_from_question("What is the protection period in Christmas Island?")
        assert result is not None
        assert result["country_code"] == "AU"


class TestFormatCountryContext:
    def test_format_has_key_fields(self):
        country = find_country("DE")
        assert country is not None
        context = format_country_context(country)
        assert "Country:" in context
        assert "Registration Period:" in context

    def test_format_skips_null_fields(self):
        context = format_country_context({"country": "Test", "madrid": None, "required_documents": None})
        assert "Madrid" not in context
        assert "Required" not in context


# --- Message building tests ---


class TestBuildMessages:
    def test_with_country_data_in_user_message(self):
        """Country data must be in user message, not system prompt."""
        messages, country_name = _build_messages("How long does trademark registration take in Germany?")
        assert country_name is not None
        assert "GERMANY" in country_name.upper()
        # System prompt stays clean
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == SYSTEM_PROMPT
        # Country data is in user message
        user_msg = messages[1]["content"]
        assert "Verified data" in user_msg
        assert "Registration Period:" in user_msg
        assert "ONLY" in user_msg

    def test_without_country(self):
        """General questions get plain user message."""
        messages, country_name = _build_messages("What is Nice classification?")
        assert country_name is None
        assert messages[0]["content"] == SYSTEM_PROMPT
        assert messages[1]["content"] == "What is Nice classification?"

    def test_bahrain_data_in_user_message(self):
        """Bahrain data must appear in user message with exact DB values."""
        messages, _ = _build_messages("How long is the registration period in Bahrain?")
        user_msg = messages[1]["content"]
        assert "Registration Period:" in user_msg
        assert "5 - 7" in user_msg  # exact value from DB

    def test_system_prompt_never_has_country_data(self):
        """System prompt must always be the base prompt, never enriched."""
        messages, _ = _build_messages("How is a trademark application filed in France?")
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
    mock_resp = _mock_together_response("Trademark registration in Germany takes approximately 3 months.")

    with patch("app.etorniegpt.service.Together") as MockTogether:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        MockTogether.return_value = mock_client

        resp = await client.post(
            "/etorniegpt",
            json={"question": "How long does trademark registration take in Germany?"},
            headers=auth_headers(admin_user),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "Germany" in data["answer"]
    assert data["country_detected"] is not None
    assert data["model"] == settings.together_etorniegpt_model


@pytest.mark.asyncio
async def test_etorniegpt_endpoint_without_country(
    client: AsyncClient,
    admin_user: User,
):
    """Endpoint works when no country is detected."""
    mock_resp = _mock_together_response("Nice classification is a system for classifying goods and services.")

    with patch("app.etorniegpt.service.Together") as MockTogether:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        MockTogether.return_value = mock_client

        resp = await client.post(
            "/etorniegpt",
            json={"question": "What is Nice classification?"},
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
            json={"question": "How is a trademark application filed in France?"},
            headers=auth_headers(admin_user),
        )

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        # System prompt is clean
        assert messages[0]["content"] == SYSTEM_PROMPT
        # Country data is in user message
        user_msg = messages[1]["content"]
        assert "Verified data" in user_msg
        assert "FRANCE" in user_msg.upper() or "FR" in user_msg


@pytest.mark.asyncio
async def test_etorniegpt_unknown_country_no_llm_call(
    client: AsyncClient,
    admin_user: User,
):
    """Country not in DB returns hardcoded response without calling LLM."""
    with patch("app.etorniegpt.service.Together") as MockTogether:
        resp = await client.post(
            "/etorniegpt",
            json={"question": "How is trademark registration done in Turkey?"},
            headers=auth_headers(admin_user),
        )

        # LLM should NOT be called
        MockTogether.return_value.chat.completions.create.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert "database" in data["answer"].lower()
    assert data["country_detected"] is None


@pytest.mark.parametrize(
    "question,expected",
    [
        # A real country named after a locative preposition -> treat as a
        # jurisdiction we have no verified data for (canned response path).
        ("How is trademark registration done in Turkey?", True),
        ("What trademark rules apply in Brazil?", True),
        # General / specific IP questions must NOT be misread as a country.
        # These regressed before: the "in"/"of" inside ordinary words wrongly
        # triggered the canned "no data" answer.
        (
            "Explain the difference between a registered trademark and an "
            "unregistered trademark?",
            False,
        ),
        ("What documents are required to file a patent application?", False),
        (
            "Which Nice classification class covers downloadable mobile software?",
            False,
        ),
        ("Can I trademark a single color for my brand?", False),
        (
            "What is the Madrid Protocol for international trademark registration?",
            False,
        ),
        ("How long does copyright protection last for a literary work?", False),
        ("Define a patent.", False),
    ],
)
def test_question_mentions_unknown_country(question, expected):
    """The country heuristic matches whole place names, not "in"/"of"
    substrings inside ordinary words."""
    assert _question_mentions_unknown_country(question) is expected

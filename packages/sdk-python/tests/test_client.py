"""SDK tests.

Integration tests run against a real, running Etornie API and are
credential-gated via environment variables. Without credentials they are
skipped (never mocked), so the suite stays green where the API is
unreachable.
"""
from __future__ import annotations

import os

import pytest

from etornie import EtornieApiError, EtornieAuthError, EtornieClient

API_URL = os.environ.get("ETORNIE_API_URL")
EMAIL = os.environ.get("ETORNIE_TEST_EMAIL")
PASSWORD = os.environ.get("ETORNIE_TEST_PASSWORD")
_LIVE = bool(API_URL and EMAIL and PASSWORD)
_requires_api = pytest.mark.skipif(
    not _LIVE,
    reason="set ETORNIE_API_URL, ETORNIE_TEST_EMAIL, ETORNIE_TEST_PASSWORD",
)


def test_base_url_required() -> None:
    with pytest.raises(ValueError):
        EtornieClient("")


def test_base_url_trailing_slash_stripped() -> None:
    assert EtornieClient("https://api.etornie.com/").base_url == (
        "https://api.etornie.com"
    )


def test_authed_call_without_token_raises() -> None:
    client = EtornieClient("https://example.invalid")
    with pytest.raises(EtornieAuthError):
        client.auth.me()


@_requires_api
def test_login_and_me() -> None:
    with EtornieClient(API_URL) as client:
        client.auth.login(EMAIL, PASSWORD)
        me = client.auth.me()
        assert me.email == EMAIL
        assert me.id


@_requires_api
def test_list_cases() -> None:
    with EtornieClient(API_URL) as client:
        client.auth.login(EMAIL, PASSWORD)
        cases, total = client.cases.list(limit=5)
        assert isinstance(cases, list)
        assert isinstance(total, int)


@_requires_api
def test_calendar_feed_lifecycle() -> None:
    with EtornieClient(API_URL) as client:
        client.auth.login(EMAIL, PASSWORD)
        try:
            enabled = client.calendar.enable()
        except EtornieApiError as exc:
            if exc.status_code == 404:
                pytest.skip("calendar feature not available on target API")
            raise
        assert enabled.enabled is True
        assert enabled.url and "/calendar/feed/" in enabled.url
        client.calendar.disable()
        assert client.calendar.status().enabled is False

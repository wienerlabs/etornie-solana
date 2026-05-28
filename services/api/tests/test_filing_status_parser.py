"""Tests for ``_parse_filing_status_code``.

EUIPO/UKIPO clients raise httpx-style ``Client error '400 Bad Request'``
errors. The parser pulls the numeric status out so the
:func:`translate_filing_error` mapping can show the right friendly
message. A missed parse falls back to the generic message — these
tests guard the regex against both shapes we have seen in the wild.
"""
from __future__ import annotations

import pytest

from app.payments.service import _parse_filing_status_code


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Client error '400 Bad Request' for url 'https://x/y'", 400),
        ("Client error '403 Forbidden' for url 'https://x/y'", 403),
        ("Server error '500 Internal Server Error' for url 'https://x/y'", 500),
        ('{"status":403,"instance":"/applicants"}', 403),
        ('{"type":"x","title":"y","status":401,"detail":"z"}', 401),
        # ASCII control char or extra whitespace must not break the match.
        ("Client error '429 Too Many Requests' for url 'https://x/y'\n", 429),
    ],
)
def test_extracts_status_code(raw: str, expected: int) -> None:
    assert _parse_filing_status_code(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "",
        "no status here",
        "404 without quoting",
        "{}",
        "status=200_but_outside_json",
    ],
)
def test_returns_none_when_no_status_present(raw: str) -> None:
    assert _parse_filing_status_code(raw) is None

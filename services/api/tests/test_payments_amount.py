"""Unit tests for ``app.payments.service._to_minor_units``.

The amount converter is the most safety-critical helper in the
payments module: a single off-by-100 mistake here ships the wrong
charge to Stripe. The tests cover the regular two-decimal currencies
we quote in (EUR, GBP, USD), the zero-decimal currencies the spec
calls out (JPY, KRW…), and the edge cases that historically slipped
through (negative input, fractional zero-decimal input,
half-up rounding on .5 cents).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.payments.service import StripeServiceError, _to_minor_units


@pytest.mark.unit
class TestStandardCurrencies:
    """Two-decimal currencies — multiply by 100, round half-up."""

    def test_eur_whole_amount(self) -> None:
        assert _to_minor_units(Decimal("900"), "EUR") == 90000

    def test_eur_two_decimals(self) -> None:
        assert _to_minor_units(Decimal("12.34"), "EUR") == 1234

    def test_gbp_uppercase_currency_code(self) -> None:
        assert _to_minor_units(Decimal("265"), "GBP") == 26500

    def test_usd_lowercase_currency_code(self) -> None:
        assert _to_minor_units(Decimal("19.99"), "usd") == 1999

    def test_chf_half_cent_rounds_up(self) -> None:
        # 0.005 CHF is a half-cent — must round to 1 cent, not down to 0.
        assert _to_minor_units(Decimal("0.005"), "CHF") == 1

    def test_chf_just_under_half_cent_rounds_down(self) -> None:
        assert _to_minor_units(Decimal("0.004"), "CHF") == 0

    def test_zero_amount(self) -> None:
        assert _to_minor_units(Decimal("0"), "EUR") == 0


@pytest.mark.unit
class TestZeroDecimalCurrencies:
    """JPY, KRW, etc. have no minor unit — amount is sent as-is."""

    def test_jpy_whole_amount(self) -> None:
        assert _to_minor_units(Decimal("1500"), "JPY") == 1500

    def test_krw_whole_amount(self) -> None:
        assert _to_minor_units(Decimal("25000"), "KRW") == 25000

    def test_jpy_fractional_amount_rejected(self) -> None:
        with pytest.raises(StripeServiceError) as exc:
            _to_minor_units(Decimal("1500.50"), "JPY")
        assert "zero-decimal" in str(exc.value)


@pytest.mark.unit
class TestInvalidInput:
    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(StripeServiceError) as exc:
            _to_minor_units(Decimal("-1.00"), "EUR")
        assert "Negative amount" in str(exc.value)

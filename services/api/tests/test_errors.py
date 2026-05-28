"""Unit tests for the user-facing error translation layer."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.errors import (
    ErrorCategory,
    UserFacingError,
    translate_filing_error,
    translate_solana_error,
    translate_stripe_error,
    translate_unknown,
)


@pytest.mark.unit
class TestUserFacingError:
    def test_carries_user_message_and_technical_detail(self) -> None:
        exc = UserFacingError(
            "Card was declined.",
            technical_detail="stripe.CardError: card_declined: insufficient_funds",
            category=ErrorCategory.payment,
            http_status=402,
        )
        assert exc.user_message == "Card was declined."
        assert "insufficient_funds" in exc.technical_detail
        assert exc.category is ErrorCategory.payment
        assert exc.http_status == 402

    def test_str_returns_user_message(self) -> None:
        exc = UserFacingError("Friendly", technical_detail="tech")
        assert str(exc) == "Friendly"

    def test_defaults(self) -> None:
        exc = UserFacingError("Friendly")
        assert exc.category is ErrorCategory.unknown
        assert exc.http_status == 400
        assert exc.technical_detail == ""


@pytest.mark.unit
class TestStripeErrorTranslation:
    """Each Stripe SDK exception type maps to a distinct user message."""

    def _stripe_exc(self, cls_name: str, message: str) -> Exception:
        """Construct a Stripe SDK exception across SDK versions.

        Stripe types have slightly different constructor signatures
        (``CardError(message, param, code)`` vs ``RateLimitError(message)``
        vs ``InvalidRequestError(message, param)``); we walk through
        the candidates until one binds so the tests do not pin to a
        specific Stripe SDK release.
        """
        import stripe

        cls = getattr(stripe, cls_name)
        candidates = [
            ((message,), {}),
            ((message, None), {}),               # InvalidRequestError(message, param)
            ((message, None, None), {}),          # CardError(message, param, code)
            ((message,), {"http_status": 400}),
        ]
        last_exc: Exception | None = None
        for args, kwargs in candidates:
            try:
                return cls(*args, **kwargs)
            except TypeError as e:
                last_exc = e
                continue
        raise AssertionError(
            f"Could not construct stripe.{cls_name} on this SDK version: {last_exc}"
        )

    def test_card_error_maps_to_402(self) -> None:
        exc = self._stripe_exc("CardError", "card_declined")
        translated = translate_stripe_error(exc)
        assert translated.http_status == 402
        assert "declined" in translated.user_message.lower()

    def test_rate_limit_error_maps_to_429(self) -> None:
        exc = self._stripe_exc("RateLimitError", "too many requests")
        translated = translate_stripe_error(exc)
        assert translated.http_status == 429
        assert "wait" in translated.user_message.lower()

    def test_invalid_request_error_maps_to_400(self) -> None:
        exc = self._stripe_exc("InvalidRequestError", "missing parameter")
        translated = translate_stripe_error(exc)
        assert translated.http_status == 400

    def test_authentication_error_maps_to_503(self) -> None:
        exc = self._stripe_exc("AuthenticationError", "invalid api key")
        translated = translate_stripe_error(exc)
        assert translated.http_status == 503

    def test_unknown_stripe_error_falls_back_to_generic(self) -> None:
        # A plain Exception (not a Stripe subclass) still gets a payment
        # category fallback so end-users never see a raw stack trace.
        translated = translate_stripe_error(ValueError("weird"))
        assert translated.category is ErrorCategory.payment


@pytest.mark.unit
class TestFilingErrorTranslation:
    def test_400_maps_to_friendly_rejection(self) -> None:
        translated = translate_filing_error(
            status_code=400, raw_detail="Application-Validation-Only"
        )
        assert translated.category is ErrorCategory.filing
        assert "rejected" in translated.user_message.lower()

    def test_401_mentions_auth_expiry(self) -> None:
        translated = translate_filing_error(status_code=401, raw_detail="expired")
        assert "expired" in translated.user_message.lower()

    def test_403_mentions_permission(self) -> None:
        translated = translate_filing_error(status_code=403, raw_detail="forbidden")
        assert "permission" in translated.user_message.lower()

    def test_429_mentions_rate_limit(self) -> None:
        translated = translate_filing_error(status_code=429, raw_detail="")
        assert "rate" in translated.user_message.lower()

    def test_unknown_status_falls_back_to_generic(self) -> None:
        translated = translate_filing_error(status_code=None, raw_detail="??")
        assert "could not be submitted" in translated.user_message.lower()

    def test_raw_detail_lands_on_technical_field(self) -> None:
        raw = "Some EUIPO error response body — should never leak."
        translated = translate_filing_error(status_code=500, raw_detail=raw)
        assert raw in translated.technical_detail
        assert raw not in translated.user_message


@pytest.mark.unit
class TestSolanaErrorTranslation:
    def test_insufficient_funds_message(self) -> None:
        translated = translate_solana_error(
            RuntimeError("InsufficientFundsForRent for account ...")
        )
        assert "sol" in translated.user_message.lower()

    def test_expired_blockhash_message(self) -> None:
        translated = translate_solana_error(
            RuntimeError("BlockhashNotFound: signature expired")
        )
        assert "expired" in translated.user_message.lower()

    def test_already_in_use_message(self) -> None:
        translated = translate_solana_error(
            RuntimeError("AlreadyInUse: PDA seed collision")
        )
        assert "already" in translated.user_message.lower()

    def test_generic_fallback(self) -> None:
        translated = translate_solana_error(RuntimeError("RPC time out"))
        assert "transaction" in translated.user_message.lower()


@pytest.mark.unit
class TestUnknownTranslator:
    def test_returns_generic_message(self) -> None:
        translated = translate_unknown(RuntimeError("boom"))
        assert translated.category is ErrorCategory.unknown
        assert "RuntimeError" in translated.technical_detail


@pytest.mark.unit
class TestFastApiHandler:
    """The handler registered in ``app.main`` should respond with the
    user_message ONLY (never the technical_detail)."""

    def test_user_message_in_response_body(self) -> None:
        from fastapi import FastAPI

        from app.errors import UserFacingError as _UF
        # Re-use the production handler against a tiny throwaway app
        # so the test does not depend on every router import succeeding
        # in the SQLite test environment.
        app = FastAPI()

        from app.main import _user_facing_error_handler

        app.add_exception_handler(_UF, _user_facing_error_handler)

        @app.get("/boom")
        def boom() -> None:
            raise _UF(
                "Friendly message",
                technical_detail="secret stack trace details",
                http_status=418,
            )

        client = TestClient(app)
        r = client.get("/boom")
        assert r.status_code == 418
        body = r.json()
        assert body["error"] == "Friendly message"
        assert "secret stack trace" not in r.text
        assert body["category"] == "unknown"

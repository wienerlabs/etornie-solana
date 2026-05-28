"""User-facing error translation layer.

Goal: never leak raw HTTP response bodies, stack traces, third-party
API JSON, or Solana RPC errors into the chat or API response that the
end user sees. The user sees a short, actionable message; the full
technical detail goes to logs (and to Sentry once that lands).

Usage
=====

Code that talks to external systems raises ``UserFacingError`` with
both a friendly ``user_message`` and the original ``technical_detail``::

    raise UserFacingError(
        user_message="Card was declined. Try another payment method.",
        technical_detail=str(exc),
        category=ErrorCategory.payment,
    )

The FastAPI exception handler (registered in ``app.main``) turns these
into a clean JSON response with only the user message, while the
original cause is logged at WARNING level with the full traceback.

Translation helpers like :func:`translate_stripe_error`,
:func:`translate_euipo_error`, and :func:`translate_solana_error` map
common third-party failure shapes to the right
``UserFacingError`` so callers do not have to duplicate the mapping.
"""
from __future__ import annotations

import enum
import logging
from typing import Final

logger = logging.getLogger(__name__)


class ErrorCategory(str, enum.Enum):
    payment = "payment"
    filing = "filing"
    on_chain = "on_chain"
    auth = "auth"
    validation = "validation"
    unknown = "unknown"


class UserFacingError(Exception):
    """An error whose ``user_message`` is safe to surface to the end user.

    ``technical_detail`` is preserved for logs and monitoring but must
    never appear in HTTP responses or chat messages.
    """

    def __init__(
        self,
        user_message: str,
        *,
        technical_detail: str | None = None,
        category: ErrorCategory = ErrorCategory.unknown,
        http_status: int = 400,
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail or ""
        self.category = category
        self.http_status = http_status

    def __repr__(self) -> str:  # pragma: no cover — debug aid only
        return (
            f"UserFacingError(category={self.category.value}, "
            f"http_status={self.http_status}, "
            f"user_message={self.user_message!r})"
        )


# ---------------------------------------------------------------------------
# Translators — third-party / domain errors -> UserFacingError
# ---------------------------------------------------------------------------


def translate_stripe_error(exc: Exception) -> UserFacingError:
    """Convert a Stripe SDK exception into a friendly user message.

    Stripe raises strongly-typed exceptions
    (``stripe.CardError``, ``stripe.RateLimitError`` …) that we map
    individually so the user sees a meaningful nudge.
    """
    # Lazy import — keeps the errors module importable even if stripe
    # is not yet installed during a build.
    try:
        import stripe  # noqa: F401
    except ImportError:  # pragma: no cover
        return UserFacingError(
            "Payment provider is temporarily unavailable. Please try again shortly.",
            technical_detail=repr(exc),
            category=ErrorCategory.payment,
            http_status=502,
        )

    name = type(exc).__name__
    detail = str(exc)[:300]

    if name == "CardError":
        return UserFacingError(
            "Your card was declined. Please try a different payment method.",
            technical_detail=detail,
            category=ErrorCategory.payment,
            http_status=402,
        )
    if name == "RateLimitError":
        return UserFacingError(
            "Too many payment attempts. Please wait a moment and try again.",
            technical_detail=detail,
            category=ErrorCategory.payment,
            http_status=429,
        )
    if name == "InvalidRequestError":
        return UserFacingError(
            "Could not start the payment session. Please refresh the page and try again.",
            technical_detail=detail,
            category=ErrorCategory.payment,
            http_status=400,
        )
    if name == "AuthenticationError":
        return UserFacingError(
            "Payment provider configuration error. Please contact support.",
            technical_detail=detail,
            category=ErrorCategory.payment,
            http_status=503,
        )
    if name in {"APIConnectionError", "APIError"}:
        return UserFacingError(
            "Payment provider is temporarily unavailable. Please try again shortly.",
            technical_detail=detail,
            category=ErrorCategory.payment,
            http_status=502,
        )
    return UserFacingError(
        "Payment could not be processed. Please try again.",
        technical_detail=f"{name}: {detail}",
        category=ErrorCategory.payment,
        http_status=400,
    )


# Trade-mark / IP office error map. Mostly classified by HTTP status
# the upstream API returned.
_EUIPO_STATUS_MAP: Final[dict[int, str]] = {
    400: "The filing payload was rejected by the IP office. Our team has been notified.",
    401: "Etornie's connection to the IP office expired. Our team has been notified and will retry shortly.",
    403: "Etornie's account does not yet have permission to file with this IP office. Our team has been notified.",
    404: "The IP office endpoint is unavailable. Please try again shortly.",
    409: "A duplicate filing was detected at the IP office. Our team will reconcile.",
    422: "Some application details were not accepted by the IP office. Our team will adjust and retry.",
    429: "The IP office is rate-limiting Etornie's submissions. Please try again in a few minutes.",
    500: "The IP office had a temporary error. We will retry shortly.",
    502: "The IP office is temporarily unavailable. We will retry shortly.",
    503: "The IP office is temporarily unavailable. We will retry shortly.",
    504: "The IP office took too long to respond. We will retry shortly.",
}


def translate_filing_error(
    *, status_code: int | None = None, raw_detail: str = ""
) -> UserFacingError:
    """Map an IP-office API failure to a friendly user message."""
    fallback = (
        "The filing could not be submitted automatically. "
        "Our team has been notified and will follow up."
    )
    message = (
        _EUIPO_STATUS_MAP.get(status_code, fallback)
        if status_code is not None
        else fallback
    )
    return UserFacingError(
        message,
        technical_detail=f"status={status_code} detail={raw_detail[:300]}",
        category=ErrorCategory.filing,
        http_status=502,
    )


def translate_solana_error(exc: Exception) -> UserFacingError:
    """Convert a Solana RPC / SDK exception into a friendly message.

    On-chain errors are notoriously cryptic; we keep the user message
    actionable while parking the raw RPC payload in logs.
    """
    detail = str(exc)[:400]
    if "InsufficientFunds" in detail or "0x1" in detail:
        return UserFacingError(
            "Wallet does not have enough SOL to pay the network fee. Top up and try again.",
            technical_detail=detail,
            category=ErrorCategory.on_chain,
            http_status=402,
        )
    if "BlockhashNotFound" in detail or "expired" in detail.lower():
        return UserFacingError(
            "The signed transaction expired before it reached the network. Please retry.",
            technical_detail=detail,
            category=ErrorCategory.on_chain,
            http_status=409,
        )
    if "AlreadyInUse" in detail or "AlreadyExists" in detail:
        return UserFacingError(
            "This action was already recorded on-chain. Refreshing should show the latest state.",
            technical_detail=detail,
            category=ErrorCategory.on_chain,
            http_status=409,
        )
    return UserFacingError(
        "The on-chain transaction could not be confirmed. Please try again shortly.",
        technical_detail=detail,
        category=ErrorCategory.on_chain,
        http_status=502,
    )


def translate_unknown(exc: Exception) -> UserFacingError:
    """Fallback translator for unrecognised exceptions."""
    return UserFacingError(
        "Something went wrong. Please try again. If the problem persists, contact support.",
        technical_detail=f"{type(exc).__name__}: {str(exc)[:300]}",
        category=ErrorCategory.unknown,
        http_status=500,
    )

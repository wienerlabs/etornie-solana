"""Exceptions raised by the Etornie SDK."""
from __future__ import annotations

from typing import Any


class EtornieError(Exception):
    """Base class for all SDK errors."""


class EtornieAuthError(EtornieError):
    """Raised when an authenticated call is made without a token."""

    def __init__(
        self,
        message: str = "No access token set. Call auth.login() or pass a token.",
    ) -> None:
        super().__init__(message)


class EtornieApiError(EtornieError):
    """Raised when the Etornie API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Etornie API error {status_code}: {detail!r}")

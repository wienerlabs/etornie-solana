"""Tests for the EUIPO OAuth refresh / re-auth path.

The actual token endpoint sits on EUIPO's sandbox infrastructure
and only their dev team can flip refresh_tokens valid / invalid.
We exercise the local logic that decides *when* to refresh, *how*
to react to a rejected refresh_token, and *which* exception type
the rest of the codebase should branch on.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.euipo.auth import (
    EuipoAuthError,
    _REFRESH_LEEWAY,
    _is_db_token_fresh_enough,
)


@pytest.mark.unit
class TestRefreshLeeway:
    """``_is_db_token_fresh_enough`` decides whether to skip the refresh.

    Tokens within the 5-minute leeway are treated as expired so the
    refresh runs while there is still budget; tokens well in the
    future bypass the refresh entirely.
    """

    def _make_payload(self, *, minutes_until_expiry: int) -> dict:
        return {
            "access_token": "abc",
            "refresh_token": "rt",
            "expires_at": datetime.now(tz=timezone.utc)
            + timedelta(minutes=minutes_until_expiry),
            "scope": "test",
        }

    def test_fresh_token_is_reused(self) -> None:
        assert _is_db_token_fresh_enough(
            self._make_payload(minutes_until_expiry=60)
        ) is True

    def test_token_within_leeway_triggers_refresh(self) -> None:
        # 4 minutes left — inside the 5-minute leeway, so treat as
        # expired. Verifies we refresh while we still have time.
        assert _is_db_token_fresh_enough(
            self._make_payload(minutes_until_expiry=4)
        ) is False

    def test_already_expired_token_triggers_refresh(self) -> None:
        assert _is_db_token_fresh_enough(
            self._make_payload(minutes_until_expiry=-30)
        ) is False

    def test_none_payload_means_no_token(self) -> None:
        assert _is_db_token_fresh_enough(None) is False

    def test_empty_access_token_means_no_token(self) -> None:
        payload = self._make_payload(minutes_until_expiry=60)
        payload["access_token"] = ""
        assert _is_db_token_fresh_enough(payload) is False

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        payload = self._make_payload(minutes_until_expiry=60)
        payload["expires_at"] = payload["expires_at"].replace(tzinfo=None)
        assert _is_db_token_fresh_enough(payload) is True

    def test_leeway_is_exactly_five_minutes(self) -> None:
        assert _REFRESH_LEEWAY == timedelta(minutes=5)


@pytest.mark.unit
class TestEuipoAuthError:
    def test_carries_status_code(self) -> None:
        exc = EuipoAuthError("invalid_grant", status_code=400)
        assert exc.status_code == 400
        assert "invalid_grant" in str(exc)

    def test_status_code_optional(self) -> None:
        exc = EuipoAuthError("no session")
        assert exc.status_code is None

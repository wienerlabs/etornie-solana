"""Tests for the Redis-backed rate limiting middleware (issue #34).

Uses the real Redis the suite already starts (see conftest.py): the point
of the middleware is a cross-worker-correct counter. conftest flushes
Redis after every test, so counters never leak between tests.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import settings
from app.security.rate_limit import resolve_client_ip
from tests.conftest import auth_headers

_BAD_LOGIN = {"email": "nobody@etornie.ch", "password": "wrong"}


@pytest.fixture(autouse=True)
def _one_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)


async def test_requests_under_the_limit_pass(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 5)
    for _ in range(5):
        resp = await client.post(
            "/auth/login",
            json=_BAD_LOGIN,
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        assert resp.status_code == 401


async def test_request_over_the_limit_gets_429(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 3)
    headers = {"X-Forwarded-For": "203.0.113.20"}

    for _ in range(3):
        resp = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers)
        assert resp.status_code == 401

    over = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers)
    assert over.status_code == 429
    assert over.json()["category"] == "rate_limit"
    assert int(over.headers["Retry-After"]) > 0


async def test_counter_is_scoped_per_ip(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 2)
    headers_a = {"X-Forwarded-For": "203.0.113.30"}
    headers_b = {"X-Forwarded-For": "203.0.113.31"}

    for _ in range(2):
        resp = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers_a)
        assert resp.status_code == 401
    blocked = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers_a)
    assert blocked.status_code == 429

    still_ok = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers_b)
    assert still_ok.status_code == 401


async def test_health_check_is_exempt_from_rate_limiting(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 1)
    monkeypatch.setattr(settings, "rate_limit_default_per_window", 1)
    headers = {"X-Forwarded-For": "203.0.113.40"}
    for _ in range(5):
        resp = await client.get("/health", headers=headers)
        assert resp.status_code == 200


async def test_disabled_rate_limiting_never_returns_429(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 1)
    headers = {"X-Forwarded-For": "203.0.113.50"}
    for _ in range(5):
        resp = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers)
        assert resp.status_code == 401


# --- client IP resolution (review item 1) ---------------------------------


def test_resolve_client_ip_takes_the_nth_entry_from_the_right() -> None:
    xff = "6.6.6.6, 198.51.100.7, 10.0.0.1"
    assert resolve_client_ip(xff, "10.0.0.9", 1) == "10.0.0.1"
    assert resolve_client_ip(xff, "10.0.0.9", 2) == "198.51.100.7"
    assert resolve_client_ip(xff, "10.0.0.9", 3) == "6.6.6.6"


def test_resolve_client_ip_ignores_the_header_without_trusted_proxies() -> None:
    assert resolve_client_ip("6.6.6.6", "10.0.0.9", 0) == "10.0.0.9"


def test_resolve_client_ip_falls_back_to_the_peer() -> None:
    assert resolve_client_ip(None, "10.0.0.9", 1) == "10.0.0.9"
    # Fewer entries than expected hops: the request skipped a proxy.
    assert resolve_client_ip("6.6.6.6", "10.0.0.9", 2) == "10.0.0.9"
    assert resolve_client_ip(None, None, 1) == "unknown"


async def test_spoofed_leftmost_forwarded_for_does_not_change_the_bucket(
    client: AsyncClient, monkeypatch
) -> None:
    """Rotating the client-controlled leftmost entry must not dodge the limit."""
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 3)
    statuses = []
    for i in range(5):
        resp = await client.post(
            "/auth/login",
            json=_BAD_LOGIN,
            headers={"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.60"},
        )
        statuses.append(resp.status_code)
    assert statuses == [401, 401, 401, 429, 429]


async def test_spoofing_a_victim_ip_does_not_burn_the_victims_bucket(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 2)
    # The attacker (203.0.113.61) claims to be the victim in the leftmost slot.
    for _ in range(3):
        await client.post(
            "/auth/login",
            json=_BAD_LOGIN,
            headers={"X-Forwarded-For": "203.0.113.99, 203.0.113.61"},
        )
    victim = await client.post(
        "/auth/login",
        json=_BAD_LOGIN,
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert victim.status_code == 401


# --- per-user scoping (review item 6) -------------------------------------


async def test_counter_is_scoped_per_user_behind_the_same_ip(
    client: AsyncClient, admin_user, client_user, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_default_per_window", 2)
    same_ip = {"X-Forwarded-For": "203.0.113.70"}
    headers_a = {**auth_headers(admin_user), **same_ip}
    headers_b = {**auth_headers(client_user), **same_ip}

    for _ in range(2):
        resp = await client.get("/auth/me", headers=headers_a)
        assert resp.status_code == 200
    blocked = await client.get("/auth/me", headers=headers_a)
    assert blocked.status_code == 429

    # Same IP, different user: independent counter.
    other = await client.get("/auth/me", headers=headers_b)
    assert other.status_code == 200


# --- 429 must look like every other response (review item 2) --------------


async def test_429_carries_cors_request_id_and_security_headers(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 1)
    headers = {
        "X-Forwarded-For": "203.0.113.80",
        "Origin": "http://localhost:3000",
    }
    first = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers)
    assert first.status_code == 401

    blocked = await client.post("/auth/login", json=_BAD_LOGIN, headers=headers)
    assert blocked.status_code == 429
    assert (
        blocked.headers["access-control-allow-origin"] == "http://localhost:3000"
    )
    assert blocked.headers.get("x-request-id")
    assert "x-content-type-options" in blocked.headers
    assert "retry-after" in blocked.headers


# --- which routes get which limit (review item 5) -------------------------


async def test_registration_gets_the_tight_limit(
    client: AsyncClient, monkeypatch
) -> None:
    """/auth/register is unauthenticated: it must not ride the 120/min default."""
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 2)
    monkeypatch.setattr(settings, "rate_limit_default_per_window", 1000)
    headers = {"X-Forwarded-For": "203.0.113.90"}

    for _ in range(2):
        resp = await client.post("/auth/register", json={}, headers=headers)
        assert resp.status_code != 429  # 422: the body is invalid
    blocked = await client.post("/auth/register", json={}, headers=headers)
    assert blocked.status_code == 429


async def test_webhooks_use_their_own_generous_bucket(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_default_per_window", 1)
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 1)
    monkeypatch.setattr(settings, "rate_limit_webhook_per_window", 3)
    headers = {"X-Forwarded-For": "203.0.113.91"}

    for _ in range(3):
        resp = await client.post(
            "/payments/stripe/webhook", content=b"{}", headers=headers
        )
        assert resp.status_code != 429
    blocked = await client.post(
        "/payments/stripe/webhook", content=b"{}", headers=headers
    )
    assert blocked.status_code == 429

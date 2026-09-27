"""Tests for the Redis-backed rate limiting middleware (issue #34).

Uses the real Redis instance the test suite already spins up (see
conftest.py) — the middleware is only meaningfully testable against a
real backend, since its whole purpose is a cross-worker-correct
counter. conftest.py flushes Redis after every test, so these tests
never see another test's counters.
"""
from __future__ import annotations

from httpx import AsyncClient

from app.config import settings


async def test_requests_under_the_limit_pass(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 5)
    for _ in range(5):
        resp = await client.post(
            "/auth/login",
            json={"email": "nobody@etornie.ch", "password": "wrong"},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        # Wrong credentials -> 401, but never 429 while under the limit.
        assert resp.status_code == 401


async def test_request_over_the_limit_gets_429(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 3)
    headers = {"X-Forwarded-For": "203.0.113.20"}

    for _ in range(3):
        resp = await client.post(
            "/auth/login",
            json={"email": "nobody@etornie.ch", "password": "wrong"},
            headers=headers,
        )
        assert resp.status_code == 401

    over_limit = await client.post(
        "/auth/login",
        json={"email": "nobody@etornie.ch", "password": "wrong"},
        headers=headers,
    )
    assert over_limit.status_code == 429
    assert over_limit.json()["category"] == "rate_limit"
    assert "Retry-After" in over_limit.headers


async def test_counter_is_scoped_per_ip(
    client: AsyncClient, monkeypatch
) -> None:
    """One client's usage must not throttle another (per-IP scoping)."""
    monkeypatch.setattr(settings, "rate_limit_auth_per_window", 2)

    headers_a = {"X-Forwarded-For": "203.0.113.30"}
    headers_b = {"X-Forwarded-For": "203.0.113.31"}

    for _ in range(2):
        resp = await client.post(
            "/auth/login",
            json={"email": "nobody@etornie.ch", "password": "wrong"},
            headers=headers_a,
        )
        assert resp.status_code == 401

    # Client A is now at its limit...
    blocked = await client.post(
        "/auth/login",
        json={"email": "nobody@etornie.ch", "password": "wrong"},
        headers=headers_a,
    )
    assert blocked.status_code == 429

    # ...but client B, a different IP, is untouched.
    still_ok = await client.post(
        "/auth/login",
        json={"email": "nobody@etornie.ch", "password": "wrong"},
        headers=headers_b,
    )
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
        resp = await client.post(
            "/auth/login",
            json={"email": "nobody@etornie.ch", "password": "wrong"},
            headers=headers,
        )
        assert resp.status_code == 401

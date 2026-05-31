"""Tests for the security response-header middleware."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.security.headers import SecurityHeadersMiddleware


def _build_app(*, enable_hsts: bool) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=enable_hsts)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    return app


async def _get_ping(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get("/ping")


class TestSecurityHeaders:
    async def test_core_headers_present(self) -> None:
        resp = await _get_ping(_build_app(enable_hsts=False))
        assert resp.status_code == 200
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert (
            resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        )
        csp = resp.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "geolocation=()" in resp.headers["permissions-policy"]
        assert resp.headers["x-xss-protection"] == "0"

    async def test_hsts_absent_when_disabled(self) -> None:
        resp = await _get_ping(_build_app(enable_hsts=False))
        assert "strict-transport-security" not in resp.headers

    async def test_hsts_present_when_enabled(self) -> None:
        resp = await _get_ping(_build_app(enable_hsts=True))
        hsts = resp.headers["strict-transport-security"]
        assert hsts.startswith("max-age=63072000")
        assert "includeSubDomains" in hsts

    async def test_headers_on_wired_app_health(self, client: AsyncClient) -> None:
        # The real app runs with environment=development in the test
        # harness, so base headers are present but HSTS is not.
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "strict-transport-security" not in resp.headers

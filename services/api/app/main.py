import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.admin.router import router as admin_router
from app.agent.router import router as agent_router
from app.ai.rag.router import router as ai_router
from app.auth.router import router as auth_router
from app.auth.wallet_router import router as wallet_auth_router
from app.braid.admin_router import router as braid_admin_router
from app.braid.router import router as braid_router
from app.cases.metadata_router import router as case_metadata_router
from app.cases.router import router as cases_router
from app.config import settings
from app.documents.router import router as documents_router
from app.esign.router import router as esign_router
from app.errors import UserFacingError
from app.observability import (
    RequestContextMiddleware,
    configure_logging,
    init_sentry,
    init_tracing,
)
from app.security.headers import SecurityHeadersMiddleware
from app.etorniegpt.router import router as etorniegpt_router
from app.in_app_notifications.router import router as in_app_notifications_router
from app.notifications.router import router as notifications_router
from app.organizations.router import router as organizations_router
from app.payments.router import router as payments_router
from app.proposals.router import router as proposals_router
from app.renewals.router import router as renewals_router
from app.required_documents.router import router as required_documents_router
from app.services.euipo.router import router as euipo_router
from app.services.ukipo.router import router as ukipo_router
from app.solana.webhook_router import router as solana_webhook_router
from app.users.router import router as users_router
from app.zk.router import router as zk_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    from app.database import engine

    configure_logging()
    init_sentry()
    init_tracing(app, engine)
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security response headers on every response. HSTS is emitted only in
# deployed environments, never over plain-HTTP local development.
app.add_middleware(
    SecurityHeadersMiddleware,
    enable_hsts=settings.environment.lower() in {"production", "staging"},
)

# Bind a request_id to every request so all of its log lines correlate; the
# caller gets it back via the X-Request-ID response header.
app.add_middleware(RequestContextMiddleware)


_user_error_logger = logging.getLogger("app.user_error")


@app.exception_handler(UserFacingError)
async def _user_facing_error_handler(
    request: Request, exc: UserFacingError
) -> JSONResponse:
    """Return only the safe ``user_message`` to the caller.

    The technical detail (third-party API body, stack trace, etc.) is
    logged at WARNING so it shows up in our logs / Sentry but never
    leaks into the API response body.
    """
    _user_error_logger.warning(
        "UserFacingError %s %s — %s — technical=%s",
        request.method,
        request.url.path,
        exc.user_message,
        exc.technical_detail,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": exc.user_message,
            "category": exc.category.value,
        },
    )


app.include_router(auth_router)
app.include_router(wallet_auth_router)
app.include_router(users_router)
app.include_router(cases_router)
app.include_router(case_metadata_router)
app.include_router(documents_router)
app.include_router(esign_router)
app.include_router(notifications_router)
app.include_router(ai_router)
app.include_router(required_documents_router)
app.include_router(in_app_notifications_router)
app.include_router(etorniegpt_router)
app.include_router(proposals_router)
app.include_router(euipo_router)
app.include_router(ukipo_router)
app.include_router(solana_webhook_router)
app.include_router(zk_router)
app.include_router(braid_router)
app.include_router(braid_admin_router)
app.include_router(agent_router)
app.include_router(payments_router)
app.include_router(renewals_router)
app.include_router(organizations_router)
app.include_router(admin_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

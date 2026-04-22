from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.ip_agent.router import router as ip_agent_router
from app.ai.rag.router import router as ai_router
from app.auth.router import router as auth_router
from app.auth.wallet_router import router as wallet_auth_router
from app.cases.metadata_router import router as case_metadata_router
from app.cases.router import router as cases_router
from app.config import settings
from app.documents.router import router as documents_router
from app.etorniegpt.router import router as etorniegpt_router
from app.in_app_notifications.router import router as in_app_notifications_router
from app.notifications.router import router as notifications_router
from app.proposals.router import router as proposals_router
from app.required_documents.router import router as required_documents_router
from app.services.euipo.router import router as euipo_router
from app.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    yield
    # Shutdown
    from app.database import engine

    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(wallet_auth_router)
app.include_router(users_router)
app.include_router(cases_router)
app.include_router(case_metadata_router)
app.include_router(documents_router)
app.include_router(notifications_router)
app.include_router(ai_router)
app.include_router(ip_agent_router)
app.include_router(required_documents_router)
app.include_router(in_app_notifications_router)
app.include_router(etorniegpt_router)
app.include_router(proposals_router)
app.include_router(euipo_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

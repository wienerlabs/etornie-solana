from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.rag.router import router as ai_router
from app.auth.router import router as auth_router
from app.cases.router import router as cases_router
from app.config import settings
from app.documents.router import router as documents_router
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
app.include_router(users_router)
app.include_router(cases_router)
app.include_router(documents_router)
app.include_router(ai_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

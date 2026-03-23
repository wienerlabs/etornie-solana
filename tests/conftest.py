import os

# Override settings BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["WHATSAPP_API_TOKEN"] = "test-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "123456"
os.environ["WHATSAPP_BUSINESS_ACCOUNT_ID"] = "789012"

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.auth.utils import create_access_token, hash_password
from app.users.models import User, UserRole
from app.cases.models import Case, CaseNote  # noqa: F401 — register models for metadata
from app.documents.models import Document  # noqa: F401 — register models for metadata
from app.ai.rag.models import DocumentChunk  # noqa: F401 — register models for metadata
from app.notifications.models import Notification  # noqa: F401
from app.agents.ip_agent.models import AgentConfig  # noqa: F401 — register models for metadata — register models for metadata

TEST_DATABASE_URL = "sqlite+aiosqlite://"

engine_test = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

async_session_test = async_sessionmaker(
    engine_test,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_test() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
async def setup_database():
    """Create tables before each test and drop after."""
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for direct DB operations in tests."""
    async with async_session_test() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_user_in_db(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    role: UserRole,
    phone: str | None = None,
) -> User:
    """Helper to insert a user directly into the DB."""
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
        phone=phone,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create an admin user."""
    return await _create_user_in_db(
        db_session,
        email="admin@etornie.ch",
        password="AdminPass123!",
        full_name="Admin User",
        role=UserRole.admin,
        phone="905001234567",
    )


@pytest.fixture
async def lawyer_user(db_session: AsyncSession) -> User:
    """Create a lawyer user."""
    return await _create_user_in_db(
        db_session,
        email="lawyer@etornie.ch",
        password="LawyerPass123!",
        full_name="Lawyer User",
        role=UserRole.lawyer,
        phone="905009876543",
    )


@pytest.fixture
async def client_user(db_session: AsyncSession) -> User:
    """Create a client user."""
    return await _create_user_in_db(
        db_session,
        email="client@etornie.ch",
        password="ClientPass123!",
        full_name="Client User",
        role=UserRole.client,
        phone="905005556677",
    )


@pytest.fixture
async def second_lawyer_user(db_session: AsyncSession) -> User:
    """Create a second lawyer user (not assigned to any case by default)."""
    return await _create_user_in_db(
        db_session,
        email="lawyer2@etornie.ch",
        password="Lawyer2Pass123!",
        full_name="Second Lawyer",
        role=UserRole.lawyer,
    )


@pytest.fixture
async def case_fixture(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> Case:
    """Create a case with client_user as client and lawyer_user as assigned lawyer."""
    from app.cases.service import create_case

    case = await create_case(
        db_session,
        title="Test IP Case",
        description="A test intellectual property case",
        case_type="trademark",
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id,
        jurisdiction="Switzerland",
    )
    return case


def auth_headers(user: User) -> dict[str, str]:
    """Generate Authorization headers with a valid access token for the given user."""
    token = create_access_token(str(user.id), user.role.value)
    return {"Authorization": f"Bearer {token}"}

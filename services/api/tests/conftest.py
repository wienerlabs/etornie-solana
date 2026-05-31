import os

# Override settings BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["WHATSAPP_API_TOKEN"] = "test-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "123456"
os.environ["WHATSAPP_BUSINESS_ACCOUNT_ID"] = "789012"
os.environ["EMAILJS_PUBLIC_KEY"] = "test-emailjs-key"
os.environ["EMAILJS_SERVICE_ID"] = "test-service-id"
os.environ["EMAILJS_TEMPLATE_ID"] = "test-template-id"
os.environ["REDIS_URL"] = "redis://localhost:6380/1"  # etornie-solana-redis, DB 1 for tests
# Required setting with no default in app.config.Settings. Set here so the suite
# is self-contained and runs in CI without a local .env file. pydantic-settings
# parses list[str] fields from JSON.
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')

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
from app.required_documents.models import RequiredDocumentTemplate, CaseRequiredDocument  # noqa: F401
from app.in_app_notifications.models import InAppNotification  # noqa: F401
from app.audit.models import AuditLog  # noqa: F401
from app.proposals.models import Proposal  # noqa: F401
from app.services.ukipo.models import UKIPOSubmission  # noqa: F401 — register models for metadata
from app.braid.models import (  # noqa: F401 — register models for metadata
    BraidBudgetState,
    BraidCalibrationEvent,
    BraidCapabilityWeight,
    BraidDecision,
    BraidDisagreementObservation,
)
from app.agent.models import (  # noqa: F401 — register models for metadata
    AgentMessage,
    AgentSession,
    CaseDraft,
    FilingAttempt,
    PaymentIntent,
)

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
    """Create tables before each test and drop after. Flush Redis test DB."""
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Reset Redis OTP module state so each test gets a fresh connection
    import app.auth.email_verification as ev
    ev._redis = None

    yield

    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Flush Redis test DB after each test
    import redis as _redis_lib
    r = _redis_lib.from_url(os.environ["REDIS_URL"])
    r.flushdb()
    r.close()


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
    """Create a staff user (admin tier).

    The historical ``lawyer`` role was retired on 2026-05-02
    (docs/REMOVED_LAWYER_LAYER.md); its capabilities collapsed into
    ``admin``. This fixture keeps the ``lawyer_user`` name for
    continuity across the existing suite but now provisions an
    admin-tier staff account.
    """
    return await _create_user_in_db(
        db_session,
        email="lawyer@etornie.ch",
        password="LawyerPass123!",
        full_name="Staff User",
        role=UserRole.admin,
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
    """Create a second non-owner client.

    Previously a second lawyer, used to assert that staff not assigned
    to a case cannot reach it. With the lawyer layer gone, the
    equivalent negative actor is a client who does not own the case.
    """
    return await _create_user_in_db(
        db_session,
        email="lawyer2@etornie.ch",
        password="Lawyer2Pass123!",
        full_name="Other Client",
        role=UserRole.client,
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

"""Integration test for the audit_logs append-only DB trigger (issue #30).

Needs a real Postgres — SQLite (the rest of the suite's DB) runs
neither Alembic migrations nor Postgres triggers, so it cannot prove
anything about the append-only guarantee. Skipped unless
AUDIT_APPEND_ONLY_TEST_DATABASE_URL is set; CI provides it via a
Postgres service container (see .github/workflows/backend-test.yml).
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

pytestmark = pytest.mark.integration

_DB_URL_ENV = "AUDIT_APPEND_ONLY_TEST_DATABASE_URL"
_SERVICES_API_DIR = Path(__file__).resolve().parents[1]


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    """Convert a 'postgresql+asyncpg://...' URL into a plain asyncpg DSN."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def postgres_url() -> str:
    url = os.environ.get(_DB_URL_ENV)
    if not url:
        pytest.skip(
            f"{_DB_URL_ENV} not set — skipping the Postgres-backed "
            "append-only trigger test (see .github/workflows/backend-test.yml)"
        )
    return url


@pytest.fixture(scope="module", autouse=True)
def _run_migrations(postgres_url: str):
    """Run `alembic upgrade head` against the Postgres test DB once.

    Runs as a subprocess, not in-process: app.config.settings is
    instantiated once at import time from the SQLite DATABASE_URL the
    rest of the suite uses (see conftest.py); alembic/env.py reads
    settings.database_url, so overriding the env var only takes effect
    in a fresh process.
    """
    env = {**os.environ, "DATABASE_URL": postgres_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_SERVICES_API_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade head failed:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    yield


async def _insert_test_user(conn: asyncpg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO users (
            id, full_name, wallet_address, auth_method, role, is_active
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        user_id,
        "Audit Test User",
        f"wallet-{user_id.hex[:16]}",
        "wallet",
        "client",
        True,
    )
    return user_id


async def _insert_audit_row(
    conn: asyncpg.Connection, actor_id: uuid.UUID
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO audit_logs (id, actor_id, action, target_type, target_id)
        VALUES ($1, $2, 'case_created', 'case', $3)
        """,
        row_id,
        actor_id,
        uuid.uuid4(),
    )
    return row_id


async def test_audit_logs_rejects_update(postgres_url: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(postgres_url))
    try:
        actor_id = await _insert_test_user(conn)
        row_id = await _insert_audit_row(conn, actor_id)

        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            await conn.execute(
                "UPDATE audit_logs SET details = 'tampered' WHERE id = $1",
                row_id,
            )
    finally:
        await conn.close()


async def test_audit_logs_rejects_delete(postgres_url: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(postgres_url))
    try:
        actor_id = await _insert_test_user(conn)
        row_id = await _insert_audit_row(conn, actor_id)

        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            await conn.execute(
                "DELETE FROM audit_logs WHERE id = $1",
                row_id,
            )
    finally:
        await conn.close()

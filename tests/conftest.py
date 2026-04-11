"""Shared test fixtures for the Workflow Automation Engine."""

import os

import asyncpg
import pytest
import redis.asyncio as aioredis
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:devpass@localhost:5435/workflows_test",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380")


@pytest.fixture(scope="session")
def _run_migrations():
    """Run Alembic migrations once per test session (synchronous fixture)."""
    import subprocess

    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic upgrade failed: {result.stderr}")
    yield
    # Downgrade after all tests complete
    subprocess.run(
        ["alembic", "downgrade", "base"],
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )


@pytest.fixture
async def async_engine():
    """Create a SQLAlchemy async engine for the test database."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(_run_migrations, async_engine):
    """Provide a transactional database session that rolls back after each test."""
    async with async_engine.connect() as conn:
        transaction = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session
        await transaction.rollback()


@pytest.fixture
async def redis_client():
    """Provide a Redis client that flushes the test database after each test."""
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def pg_pool():
    """Raw asyncpg connection pool for smoke tests."""
    raw_url = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(raw_url)
    yield pool
    await pool.close()

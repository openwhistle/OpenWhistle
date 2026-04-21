"""Shared test fixtures for OpenWhistle tests."""

import os
import subprocess
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Set test environment before importing app modules
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://openwhistle:openwhistle@localhost:5432/openwhistle_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")  # DB 1 for tests
os.environ.setdefault("DEMO_MODE", "false")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

_ENUM_TYPES = ["reportcategory", "reportstatus", "reportsender"]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine() -> AsyncGenerator[AsyncEngine]:
    """Session-scoped: runs alembic migrations once for the entire test session."""
    from app.config import settings

    engine = create_async_engine(settings.database_url, echo=False)

    # Full clean slate: drop tables + raw enum types + alembic tracking table
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        for enum_type in _ENUM_TYPES:
            await conn.execute(text(f"DROP TYPE IF EXISTS {enum_type} CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))

    # Apply migrations once for the whole session
    result = subprocess.run(  # noqa: S603
        ["alembic", "upgrade", "head"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Test DB migration failed:\n{result.stderr}")

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        for enum_type in _ENUM_TYPES:
            await conn.execute(text(f"DROP TYPE IF EXISTS {enum_type} CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Function-scoped session using NullPool — avoids cross-loop connection reuse."""
    from app.config import settings

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncGenerator[AsyncClient]:
    """HTTP test client — overrides get_db with NullPool to avoid cross-loop errors."""
    from app.config import settings

    test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    await test_engine.dispose()

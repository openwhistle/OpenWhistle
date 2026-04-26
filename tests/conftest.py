"""Shared test fixtures for OpenWhistle tests."""

import os
import re
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

_ENUM_TYPES = ["reportcategory", "reportstatus", "reportsender", "submissionmode", "adminrole"]

# Step number for the location step in the wizard (only active when locations exist)
_STEP_LOCATION = 2


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


@pytest_asyncio.fixture(loop_scope="function")
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Function-scoped session using NullPool — avoids cross-loop connection reuse."""
    from app.config import settings

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def client(db_engine: AsyncEngine) -> AsyncGenerator[AsyncClient]:
    """HTTP test client — fresh DB + Redis connections per test to avoid cross-loop errors."""
    from app.config import settings
    from app.redis_client import close_redis

    # Reset Redis so the next request creates a fresh connection on this loop
    await close_redis()

    test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Use https://test so that Secure cookies (set when DEMO_MODE=false) are
    # included in requests. The ASGI transport does not perform real TLS.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        follow_redirects=True,
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    await test_engine.dispose()
    await close_redis()  # Clean up so next test starts fresh


def _wizard_get_csrf(response_text: str) -> str:
    """Extract the CSRF token from a wizard step HTML response."""
    m = re.search(r'name="csrf_token" value="([^"]+)"', response_text)
    return m.group(1) if m else ""


def _wizard_detect_step(response_text: str) -> int:
    """Detect the current wizard step number from the hidden step input."""
    m = re.search(r'name="step" value="(\d+)"', response_text)
    return int(m.group(1)) if m else 1


async def _wizard_skip_location_if_needed(
    client: AsyncClient, resp_after_step1_text: str
) -> tuple[str, str]:
    """If the wizard is on the location step (step 2), skip it with an empty location.

    Returns (updated_response_text, csrf_for_next_step).
    The returned text is the response after the location step (i.e., step 3 / category).
    If no location step, returns the original text unchanged.
    """
    current_step = _wizard_detect_step(resp_after_step1_text)
    if current_step != _STEP_LOCATION:
        return resp_after_step1_text, _wizard_get_csrf(resp_after_step1_text)

    # Location step is active — submit with no location_id (optional field)
    csrf = _wizard_get_csrf(resp_after_step1_text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(current_step),
        "action": "next",
        "location_id": "",
    })
    return resp.text, _wizard_get_csrf(resp.text)


async def wizard_submit(
    client: AsyncClient,
    category: str = "financial_fraud",
    description: str = "This is a test report with enough characters to pass validation.",
    submission_mode: str = "anonymous",
) -> tuple[str, str]:
    """Walk the full multi-step submission wizard and return (case_number, pin).

    Handles both with-locations and without-locations wizard flows automatically.

    Steps (no locations active):
      1 → mode selection
      3 → category
      4 → description
      5 → attachments (skip)
      6 → review + final submit

    Steps (locations active):
      1 → mode selection
      2 → location (skip with empty location_id)
      3 → category
      4 → description
      5 → attachments (skip)
      6 → review + final submit
    """
    # Step 1: mode selection
    get_resp = await client.get("/submit")
    csrf = _wizard_get_csrf(get_resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": "1",
        "action": "next",
        "submission_mode": submission_mode,
    })

    # Step 2 (location — conditional): skip if present
    resp_text, csrf = await _wizard_skip_location_if_needed(client, resp.text)

    # Step 3: category
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_wizard_detect_step(resp_text)),
        "action": "next",
        "category": category,
    })

    # Step 4: description
    csrf = _wizard_get_csrf(resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_wizard_detect_step(resp.text)),
        "action": "next",
        "description": description,
    })

    # Step 5: attachments (skip — no files)
    csrf = _wizard_get_csrf(resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_wizard_detect_step(resp.text)),
        "action": "next",
    })

    # Step 6: review + final submit
    csrf = _wizard_get_csrf(resp.text)
    resp = await client.post("/submit", data={
        "csrf_token": csrf,
        "step": str(_wizard_detect_step(resp.text)),
        "action": "next",
    })

    # Extract case number and PIN from success page
    cn_m = re.search(r"OW-\d{4}-\d{5}", resp.text)
    case_number = cn_m.group(0) if cn_m else ""
    pin_m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", resp.text
    )
    pin = pin_m.group(1) if pin_m else ""
    return case_number, pin

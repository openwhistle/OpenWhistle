"""Shared test fixtures for OpenWhistle tests."""

import os
import re
import subprocess
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
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

# Ensure new v1.0.0 feature flags are off in tests
os.environ.setdefault("RETENTION_ENABLED", "false")
os.environ.setdefault("MULTI_TENANCY_ENABLED", "false")

# Step number for the location step in the wizard (only active when locations exist)
_STEP_LOCATION = 2


def _is_safe_to_flush(redis_url: str) -> bool:
    """True only for a local Redis URL on a non-default DB index.

    Guards ``_flush_test_redis`` below: DB 0 (what a misconfigured/missing
    REDIS_URL falls back to) and any non-local host are refused, so a bad
    env can never flush a real Redis instance.
    """
    parsed = urlparse(redis_url)
    host = parsed.hostname or ""
    try:
        db_index = int((parsed.path or "").lstrip("/") or "0")
    except ValueError:
        db_index = 0
    return host in ("localhost", "127.0.0.1") and db_index != 0


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _flush_test_redis() -> None:
    """Flush the test Redis DB once per session.

    A long-lived test Redis keeps rate-limit/lockout keys between runs;
    without this, a second run in a row sees stale counters and gets 429s
    that cascade into unrelated failures.
    """
    from app.config import settings

    if not _is_safe_to_flush(settings.redis_url):
        return
    from redis.asyncio import from_url

    redis = await from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()


async def _drop_test_schema(conn: AsyncConnection) -> None:
    """Drop every app table, raw enum type, and the alembic tracking table.

    Shared by ``db_engine``'s setup (clean slate before migrating) and
    teardown (clean slate after the session) so both halves stay in sync --
    see ``test_drop_test_schema_leaves_no_tables_and_no_alembic_version``
    for the behavioural guard on this.
    """
    await conn.run_sync(Base.metadata.drop_all)
    for enum_type in _ENUM_TYPES:
        await conn.execute(text(f"DROP TYPE IF EXISTS {enum_type} CASCADE"))
    await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine() -> AsyncGenerator[AsyncEngine]:
    """Session-scoped: runs alembic migrations once for the entire test session."""
    from app.config import settings

    engine = create_async_engine(settings.database_url, echo=False)

    async with engine.begin() as conn:
        await _drop_test_schema(conn)

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

    # Leaving alembic_version at head with no tables underneath it breaks a
    # later `alembic downgrade` run against this same database (it thinks
    # the schema is already migrated) -- so the teardown must drop it too.
    async with engine.begin() as conn:
        await _drop_test_schema(conn)
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


async def setup_token() -> str:
    """The current one-time setup token, created if missing (as GET /setup does)."""
    from app.redis_client import get_redis
    from app.services.setup_token import SETUP_TOKEN_KEY, ensure_setup_token

    redis = await get_redis()
    await ensure_setup_token(redis)
    raw = await redis.get(SETUP_TOKEN_KEY)
    return raw.decode() if isinstance(raw, bytes) else str(raw)


@pytest_asyncio.fixture(loop_scope="function")
async def throwaway_db(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """An isolated Postgres database for a test that touches *every* row — a
    key-rotation script, an alembic downgrade/upgrade — so the shared test DB
    and every other test's rows are never rewritten.

    Creates a uniquely named database on the same server, migrates it with
    alembic (subprocess, DATABASE_URL overridden), points settings.database_url
    at it (so a subprocess given ``settings.database_url`` uses it too), yields
    an AsyncSession on it, and drops the database in a finally.
    """
    import uuid

    from sqlalchemy.engine import make_url

    from app.config import settings

    base_url = make_url(settings.database_url)
    db_name = f"openwhistle_tmp_{uuid.uuid4().hex[:12]}"
    admin_url = base_url.set(database="postgres")

    admin_engine = create_async_engine(admin_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    tmp_url = base_url.set(database=db_name)
    engine = None
    try:  # everything after CREATE DATABASE: a failing migration must not leak it
        result = subprocess.run(  # noqa: S603
            ["alembic", "upgrade", "head"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "DATABASE_URL": tmp_url.render_as_string(hide_password=False)},
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to migrate throwaway DB {db_name}:\n{result.stderr}")

        monkeypatch.setattr(settings, "database_url", tmp_url.render_as_string(hide_password=False))

        engine = create_async_engine(tmp_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        if engine is not None:
            await engine.dispose()
        admin_engine = create_async_engine(
            admin_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()

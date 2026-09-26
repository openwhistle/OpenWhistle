"""Unit tests for fixture guards in conftest.py.

Most of these only exercise pure guard logic and need no live services;
one (below) verifies a schema-drop helper's actual effect on a real
Postgres database.
"""

import os
import subprocess
from urllib.parse import urlsplit, urlunsplit

import pytest
from conftest import _drop_test_schema, _is_safe_to_flush
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def test_refuses_db_0() -> None:
    """DB 0 is the conventional default a misconfigured env would fall back to."""
    assert _is_safe_to_flush("redis://localhost:6379/0") is False


def test_refuses_missing_db_index() -> None:
    """No path at all means DB 0."""
    assert _is_safe_to_flush("redis://localhost:6379") is False


def test_refuses_non_local_host() -> None:
    assert _is_safe_to_flush("redis://prod.example.com:6379/1") is False


def test_refuses_non_local_host_even_on_a_safe_db_index() -> None:
    assert _is_safe_to_flush("redis://10.0.0.5:6379/5") is False


def test_allows_localhost_non_zero_db() -> None:
    assert _is_safe_to_flush("redis://localhost:6379/1") is True


def test_allows_127_0_0_1_non_zero_db() -> None:
    assert _is_safe_to_flush("redis://127.0.0.1:6380/1") is True


def test_refuses_non_numeric_db_index() -> None:
    """An unparsable path falls back to db 0 (refused), not an exception."""
    assert _is_safe_to_flush("redis://localhost:6379/notanumber") is False


def _throwaway_db_url(base_url: str, dbname: str) -> str:
    """Same host/port/credentials as ``base_url``, pointed at ``dbname``."""
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{dbname}", parts.query, parts.fragment))


@pytest.mark.asyncio
async def test_drop_test_schema_leaves_no_tables_and_no_alembic_version() -> None:
    """Behavioural regression guard.

    A source-text check (grepping ``db_engine`` for the string
    "alembic_version") has two failure modes: it stays green if a future
    edit removes the actual DROP TABLE but leaves a comment mentioning the
    name, and it breaks on a harmless refactor that moves the drop logic
    into a helper. This instead runs the real helper against a real,
    throwaway Postgres database that has been migrated to head, and checks
    via ``information_schema.tables`` that both the app tables and
    ``alembic_version`` are actually gone afterward.
    """
    from app.config import settings

    dbname = "ow_test_x4_throwaway"
    # The lane's own test DB, used only as a connection to issue CREATE/DROP DATABASE.
    admin_url = settings.database_url
    throwaway_url = _throwaway_db_url(admin_url, dbname)

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))
            await conn.execute(text(f'CREATE DATABASE "{dbname}"'))

        result = subprocess.run(  # noqa: S603
            ["alembic", "upgrade", "head"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "DATABASE_URL": throwaway_url},
        )
        assert result.returncode == 0, result.stderr

        throwaway_engine = create_async_engine(throwaway_url)
        try:
            async with throwaway_engine.begin() as conn:
                before = (await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )).scalars().all()
                assert "alembic_version" in before  # sanity: migrated to head first

                await _drop_test_schema(conn)

                after = (await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )).scalars().all()
                assert after == []
        finally:
            await throwaway_engine.dispose()

        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))
    finally:
        await admin_engine.dispose()

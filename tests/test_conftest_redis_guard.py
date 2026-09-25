"""Unit tests for fixture guards in conftest.py.

No live Redis/Postgres needed — these only exercise pure guard logic and
the shape of ``conftest.py`` itself.
"""

import inspect

from conftest import _is_safe_to_flush, db_engine


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


def test_db_engine_teardown_also_drops_alembic_version() -> None:
    """Regression guard (task X4): the session teardown must drop
    ``alembic_version`` along with the tables/enums it already drops.

    Without it, ``alembic_version`` survives at head with no tables
    underneath it, so a later ``alembic downgrade`` against the same
    database fails as if the schema were already migrated.
    """
    source = inspect.getsource(db_engine)
    setup, teardown = source.split("yield engine", 1)
    assert "alembic_version" in setup
    assert "alembic_version" in teardown

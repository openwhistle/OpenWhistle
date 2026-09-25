"""Unit tests for the test-Redis flush guard in conftest.py (task X1 / OPEN-2).

No live Redis needed — this only exercises the pure URL-parsing guard that
decides whether ``_flush_test_redis`` is allowed to run.
"""

from conftest import _is_safe_to_flush


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

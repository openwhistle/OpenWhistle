"""v1.6.0 deployment guards: migrations, configuration and the onion header."""

from __future__ import annotations

import subprocess

import pytest


@pytest.mark.parametrize(
    "direction", [("upgrade", "7d4e2b9c1a05:a1c6e0f4b201"), ("downgrade", "a1c6e0f4b201:7d4e2b9c1a05")]
)
def test_migration_004_refuses_offline_sql(direction: tuple[str, str]) -> None:
    """--sql would emit only the ALTER and leave the TOTP secrets unencrypted."""
    run = subprocess.run(  # noqa: S603
        ["alembic", direction[0], direction[1], "--sql"],  # noqa: S607
        capture_output=True, text=True, check=False,
    )
    assert run.returncode != 0
    assert "must run online" in run.stderr

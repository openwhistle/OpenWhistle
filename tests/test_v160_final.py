"""v1.6.0 final-review guards: one test per finding."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

_ROOT = Path(__file__).resolve().parent.parent


# --- I7: database errors carry no bound parameters ---------------------------------------


async def test_db_error_log_line_has_no_bound_parameter(caplog: pytest.LogCaptureFixture) -> None:
    from app.database import engine

    case_number = "OW-SECRET-CASE-4711"
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("SELECT CAST(:v AS text), 1 / 0"), {"v": case_number})
        with caplog.at_level(logging.ERROR):
            logging.getLogger("uvicorn.error").error("request failed", exc_info=exc_info.value)
    finally:
        await engine.dispose()
    assert case_number not in str(exc_info.value)
    assert case_number not in caplog.text


def test_every_engine_hides_parameters() -> None:
    offenders = []
    sources = [*_ROOT.glob("app/**/*.py"), *_ROOT.glob("scripts/*.py"), _ROOT / "migrations/env.py"]
    for path in sources:
        source = path.read_text()
        for match in re.finditer(r"(create_async_engine|async_engine_from_config)\(", source):
            depth, i = 1, match.end()
            while depth:
                depth += {"(": 1, ")": -1}.get(source[i], 0)
                i += 1
            if "hide_parameters=True" not in source[match.end():i]:
                line = source[:match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(_ROOT)}:{line}")
    assert offenders == []


# --- I6: the digest is no more precise than the stored day --------------------------------


def test_notification_digest_defaults_to_one_day() -> None:
    from app.config import Settings

    assert Settings.model_fields["notification_batch_minutes"].default == 1440
    compose = (_ROOT / "docker-compose.prod.yml").read_text()
    assert '"${NOTIFICATION_BATCH_MINUTES:-1440}"' in compose
    values = (_ROOT / "charts/openwhistle/values.yaml").read_text()
    assert 'notificationBatchMinutes: "1440"' in values


# --- I2: a key change that leaves existing data unreadable refuses to start ---------------

_KEY_A = "a" * 40
_KEY_B = "b" * 40


async def _seed_report_and_admin(db) -> None:  # type: ignore[no-untyped-def]
    import uuid

    import pyotp

    from app.models.user import AdminUser
    from app.services.report import create_report

    await create_report(db, "corruption", "Written under the key configured at the time.")
    db.add(AdminUser(
        id=uuid.uuid4(), username=f"key-{uuid.uuid4().hex[:8]}", totp_secret=pyotp.random_base32(),
    ))
    await db.commit()


async def test_setting_encryption_key_without_previous_is_detected(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from app.config import settings
    from app.services.encryption import configured_keys_read_existing_data

    monkeypatch.setattr(settings, "encryption_key", "")
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    await _seed_report_and_admin(throwaway_db)
    assert await configured_keys_read_existing_data()

    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    assert not await configured_keys_read_existing_data()
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    assert await configured_keys_read_existing_data()


async def test_removing_encryption_key_is_detected(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from app.config import settings
    from app.services.encryption import configured_keys_read_existing_data

    monkeypatch.setattr(settings, "encryption_key", _KEY_A)
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    await _seed_report_and_admin(throwaway_db)
    monkeypatch.setattr(settings, "encryption_key", "")
    assert not await configured_keys_read_existing_data()


async def test_an_unreadable_totp_secret_alone_is_detected(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """No report yet: the admins' second factor alone must still stop the start."""
    import uuid

    from app.config import settings
    from app.models.user import AdminUser
    from app.services.encryption import configured_keys_read_existing_data

    monkeypatch.setattr(settings, "encryption_key", _KEY_A)
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    throwaway_db.add(
        AdminUser(id=uuid.uuid4(), username="totp-only", totp_secret="JBSWY3DPEHPK3PXP")
    )
    await throwaway_db.commit()
    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    assert not await configured_keys_read_existing_data()


async def test_a_database_without_tables_passes_the_key_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.engine import make_url

    from app.config import settings
    from app.services.encryption import configured_keys_read_existing_data

    empty = make_url(settings.database_url).set(database="postgres")
    monkeypatch.setattr(settings, "database_url", empty.render_as_string(hide_password=False))
    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    assert await configured_keys_read_existing_data()


async def test_startup_refuses_before_migrating_when_data_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI

    from app.main import lifespan

    with (
        patch("app.services.encryption.configured_keys_read_existing_data",
              new_callable=AsyncMock, return_value=False),
        patch("app.main._run_alembic_upgrade") as upgrade,
        pytest.raises(RuntimeError, match="ENCRYPTION_KEY_PREVIOUS"),
    ):
        async with lifespan(FastAPI()):
            pass
    upgrade.assert_not_called()


async def test_rotation_script_names_the_key_mismatch(
    throwaway_db, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    import importlib.util

    from app.config import settings
    from app.services.encryption import UNREADABLE_DATA_MESSAGE

    await _seed_report_and_admin(throwaway_db)
    monkeypatch.setattr(settings, "encryption_key", _KEY_B)
    monkeypatch.setattr(settings, "encryption_key_previous", _KEY_A)  # the wrong old key
    spec = importlib.util.spec_from_file_location("rot", _ROOT / "scripts/rotate_encryption_key.py")
    assert spec and spec.loader
    rot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rot)
    assert await rot.main() == 1
    assert UNREADABLE_DATA_MESSAGE in capsys.readouterr().out

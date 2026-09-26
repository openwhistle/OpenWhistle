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
    for path in [*_ROOT.glob("app/**/*.py"), *_ROOT.glob("scripts/*.py"), _ROOT / "migrations/env.py"]:
        source = path.read_text()
        for match in re.finditer(r"(create_async_engine|async_engine_from_config)\(", source):
            depth, i = 1, match.end()
            while depth:
                depth += {"(": 1, ")": -1}.get(source[i], 0)
                i += 1
            if "hide_parameters=True" not in source[match.end():i]:
                offenders.append(f"{path.relative_to(_ROOT)}:{source[:match.start()].count(chr(10)) + 1}")
    assert offenders == []

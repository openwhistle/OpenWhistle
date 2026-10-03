"""CI's test job installs no Playwright; the scripts must import without it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import importlib.util, sys
sys.modules["playwright"] = None  # import playwright -> ImportError
sys.modules["playwright.sync_api"] = None
spec = importlib.util.spec_from_file_location("m", sys.argv[1])
spec.loader.exec_module(importlib.util.module_from_spec(spec))
"""


@pytest.mark.parametrize("script", ["compare_site_screens", "render_icons"])
def test_script_imports_without_playwright(script: str) -> None:
    result = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [sys.executable, "-c", _PROBE, str(ROOT / "scripts" / f"{script}.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

"""Guards for scripts/take_screenshots.py.

The screenshots live in openwhistle/website, which checks that every one has its
light and dark twin and that every name in this script has both files.
"""

import importlib.util
import re
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts" / "take_screenshots.py"
CSS_PATH = ROOT / "app" / "static" / "css" / "site.css"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


@cache
def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("take_screenshots", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve the script's annotations through it
    spec.loader.exec_module(module)
    return module


def test_without_a_website_checkout_the_script_refuses_to_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The screenshots are the website's files: no default path in this repository."""
    monkeypatch.delenv("OW_WEBSITE_CHECKOUT", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        _script().out_dir([])
    assert exit_info.value.code == 2
    assert "OW_WEBSITE_CHECKOUT" in capsys.readouterr().err


def test_a_folder_that_is_no_website_checkout_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OW_WEBSITE_CHECKOUT", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        _script().out_dir(["--out", str(tmp_path)])
    assert exit_info.value.code == 2


def test_the_checkout_comes_from_the_flag_or_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    screens = tmp_path / _script().SCREENS
    screens.mkdir(parents=True)
    monkeypatch.setenv("OW_WEBSITE_CHECKOUT", str(tmp_path))
    assert _script().out_dir([]) == screens
    monkeypatch.delenv("OW_WEBSITE_CHECKOUT")
    assert _script().out_dir(["--out", str(tmp_path)]) == screens


def test_viewport_is_above_the_admin_two_column_breakpoint() -> None:
    """VIEWPORT_WIDTH in scripts/take_screenshots.py must stay wider than the
    max-width at which `.admin-shell` (app/static/css/site.css) drops its
    sidebar to a single column.

    Without this, every admin screenshot (login excepted) would show the
    collapsed single-column fallback instead of the two-column layout the
    docs are meant to show — the same defect easywall's
    TestScreenshotsAreTakenAboveTheTwoColumnBreakpoint guards against, and for
    the same reason: the breakpoint and the viewport are two numbers in two
    files, and lowering either one re-creates it independently.
    """
    css = CSS_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"@media\s*\(max-width:\s*(\d+)px\)\s*\{\s*\.admin-shell\s*\{\s*"
        r"grid-template-columns:\s*minmax\(0,\s*1fr\)",
        css,
    )
    assert m, "no `.admin-shell` single-column media query found in app/static/css/site.css"
    breakpoint_px = int(m.group(1))

    script = _script_text()
    vm = re.search(r"VIEWPORT_WIDTH\s*=\s*(\d+)", script)
    assert vm, (
        "scripts/take_screenshots.py no longer declares VIEWPORT_WIDTH in the shape this test reads"
    )
    width = int(vm.group(1))

    assert width > breakpoint_px, (
        f"screenshots are taken at {width}px, but .admin-shell collapses to one column "
        f"at or below {breakpoint_px}px — every admin screenshot would show the narrow "
        "fallback layout instead of the two-column one being documented"
    )


def test_shoot_grows_the_viewport_instead_of_capturing_full_page() -> None:
    """shoot() must resize the viewport to the page's height and never pass
    full_page=True.

    `.admin-menu` is `position: sticky` and the session-expiry banner is
    `position: fixed`; a full_page capture leaves either one laid out against
    the viewport it was rendered in rather than tracking the grown page —
    the same hazard easywall's
    TestScreenshotsGrowTheWindowInsteadOfCapturingBeyondIt guards against.
    """
    script = _script_text()
    start = script.index("def shoot(")
    end = script.index("\ndef ", start + 1)
    body = script[start:end]
    # Strip the docstring: it names `full_page=True` in prose, as the very
    # thing this guard forbids in the code below it.
    body = re.sub(r'""".*?"""', "", body, count=1, flags=re.DOTALL)

    assert "full_page=True" not in body, "shoot() must not capture with full_page=True"
    assert "set_viewport_size" in body, (
        "shoot() must grow the viewport to the page's height before capturing"
    )

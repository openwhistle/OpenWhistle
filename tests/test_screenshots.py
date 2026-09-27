"""Guards for docs/img/screens/ and scripts/take_screenshots.py.

That every screenshot is embedded, with its dark twin and alt text, is
tests/test_docs_figures.py's job.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCREENS_DIR = ROOT / "docs" / "img" / "screens"
SCRIPT_PATH = ROOT / "scripts" / "take_screenshots.py"
CSS_PATH = ROOT / "app" / "static" / "css" / "site.css"

_THEMES = ("light", "dark")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _names_in_script() -> list[str]:
    return re.findall(r'Screenshot\(\s*"([\w-]+)"', _script_text())


def test_every_screenshot_has_a_light_and_dark_twin() -> None:
    files = list(SCREENS_DIR.glob("*.png"))
    assert files, f"no screenshots found in {SCREENS_DIR}"

    names = {re.sub(r"-(light|dark)$", "", p.stem) for p in files}
    missing = [
        f"{name}-{theme}.png"
        for name in sorted(names)
        for theme in _THEMES
        if not (SCREENS_DIR / f"{name}-{theme}.png").exists()
    ]
    assert not missing, f"screenshot missing its light/dark twin: {missing}"


def test_every_name_in_the_script_has_both_files() -> None:
    """Catches a name added, removed or renamed in SCREENSHOTS without
    re-running the script — the list and docs/img/screens/ drift apart
    silently otherwise."""
    names = _names_in_script()
    assert names, "could not parse any Screenshot(...) entries out of scripts/take_screenshots.py"

    missing = [
        f"{name}-{theme}.png"
        for name in names
        for theme in _THEMES
        if not (SCREENS_DIR / f"{name}-{theme}.png").exists()
    ]
    assert not missing, f"scripts/take_screenshots.py lists a name with no rendered file: {missing}"


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

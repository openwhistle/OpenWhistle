"""The app's static fonts stay full: never subset to a few characters.

The website's variable fonts and their cuts are checked in openwhistle/website.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]


def test_the_apps_static_fonts_stay_full() -> None:
    """The app image and the diagram geometry use app/static/fonts as they are."""
    static_fonts = sorted((ROOT / "app" / "static" / "fonts").glob("*.woff2"))
    assert len(static_fonts) == 6
    for path in static_fonts:
        assert len(TTFont(path).getBestCmap()) > 220, path.name

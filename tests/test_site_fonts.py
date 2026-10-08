"""The site ships subset fonts: every character the pages draw, all of Latin-1, and nothing else."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from tests.built_site import builder, built, pages

ROOT = Path(__file__).resolve().parents[1]
FACES = sorted(p.name for p in (ROOT / "docs" / "fonts").glob("*.woff2"))


class _Text(HTMLParser):
    """Text a browser may draw: text nodes, alt/title/aria-label/placeholder, not script/style."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chars: set[str] = set()
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if name in ("alt", "title", "aria-label", "placeholder") and value:
                self.chars |= set(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chars |= set(data)


def _unescape(m: re.Match[str]) -> str:
    return chr(int(m.group(1), 16))


def _css_content_text() -> set[str]:
    chars: set[str] = set()
    for sheet in (built() / "assets" / "css").glob("*.css"):
        css = sheet.read_text(encoding="utf-8")
        for decl in re.findall(r"(?<![\w-])content\s*:([^;}]*)", css):
            # An escape pair or one plain character, never both readings: no backtracking blow-up.
            for _, string in re.findall(r"(['\"])((?:\\.|(?!\1)[^\\])*)\1", decl):
                string = re.sub(r"\\([0-9a-fA-F]{1,6})\s?", _unescape, string)
                chars |= set(string)
    return chars


def _visible_text() -> set[str]:
    parser = _Text()
    for path in pages():
        parser.feed(path.read_text(encoding="utf-8"))
    return {c for c in parser.chars | _css_content_text() if c.isprintable() and not c.isspace()}


@pytest.mark.parametrize("face", FACES)
def test_every_drawn_character_the_font_has_is_in_its_subset(face: str) -> None:
    full = set(TTFont(ROOT / "docs" / "fonts" / face).getBestCmap())
    subset = set(TTFont(built() / "fonts" / face).getBestCmap())
    wanted = {ord(c) for c in _visible_text() | set(builder().FONT_TEXT_EXTRA)} & full
    missing = sorted(chr(c) for c in wanted - subset)
    assert not missing, f"{face} subset lacks {missing}"


@pytest.mark.parametrize("face", FACES)
def test_every_latin1_letter_is_kept_for_typed_text(face: str) -> None:
    full = set(TTFont(ROOT / "docs" / "fonts" / face).getBestCmap())
    subset = set(TTFont(built() / "fonts" / face).getBestCmap())
    latin1 = set(range(0xA0, 0x100)) & full
    assert latin1 <= subset, face


def test_the_subsets_are_smaller() -> None:
    total_full = sum((ROOT / "docs" / "fonts" / f).stat().st_size for f in FACES)
    total_sub = sum((built() / "fonts" / f).stat().st_size for f in FACES)
    assert total_sub < total_full, (total_sub, total_full)


def test_the_source_fonts_stay_full() -> None:
    """The app image and the diagram geometry use docs/fonts as they are."""
    for face in FACES:
        assert len(TTFont(ROOT / "docs" / "fonts" / face).getBestCmap()) > 220, face


@pytest.mark.parametrize("face", FACES)
def test_the_subset_keeps_tabular_figures(face: str) -> None:
    """The site sets tabular-nums; the subsetter's default feature list drops `tnum`."""

    def tags(path: Path) -> set[str]:
        gsub = TTFont(path).get("GSUB")
        return {r.FeatureTag for r in gsub.table.FeatureList.FeatureRecord} if gsub else set()

    if "tnum" in tags(ROOT / "docs" / "fonts" / face):
        assert "tnum" in tags(built() / "fonts" / face), face

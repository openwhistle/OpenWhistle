"""The site ships subset fonts: every character the pages draw, all of Latin-1, and nothing else."""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from tests.built_site import builder, built, pages

ROOT = Path(__file__).resolve().parents[1]
FACES = sorted(p.name for p in (ROOT / "docs" / "fonts").glob("*.woff2"))


def _visible_text() -> set[str]:
    chars: set[str] = set()
    for path in pages():
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"<(script|style)\b.*?</\1>", "", text, flags=re.S)
        chars |= set(html_lib.unescape(re.sub(r"<[^>]+>", "", text)))
    return {c for c in chars if c.isprintable() and not c.isspace()}


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

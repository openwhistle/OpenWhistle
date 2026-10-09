"""The site ships three variable fonts cut to the characters the pages draw, and nothing else."""

from __future__ import annotations

import base64
import io
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from tests.built_site import builder, built, pages

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "docs" / "_fonts"
# built name -> (source file, wght range kept or None for one pinned instance)
FACES = {
    "sora-variable.woff2": ("Sora[wght].ttf", (300, 700)),
    "jetbrains-mono-variable.woff2": ("JetBrainsMono[wght].ttf", (400, 700)),
    "jetbrains-mono-italic-variable.woff2": ("JetBrainsMono-Italic[wght].ttf", None),
}


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


def _built(face: str) -> TTFont:
    """The subset font as the browser gets it: decoded from the data: URI of its stylesheet."""
    sheet = "fonts-italic.css" if "italic" in face else "fonts.css"
    css = (built() / "assets" / "css" / sheet).read_text(encoding="utf-8")
    family = "Sora" if face.startswith("sora") else "JetBrains Mono"
    match = re.search(
        rf"font-family: '{family}'; src: url\('data:font/woff2;base64,([^']+)'\)", css
    )
    assert match, f"{sheet} carries no {family}"
    return TTFont(io.BytesIO(base64.b64decode(match.group(1))))


def _source(face: str) -> TTFont:
    return TTFont(SOURCES / FACES[face][0])


def _tags(font: TTFont) -> set[str]:
    gsub = font.get("GSUB")
    return {r.FeatureTag for r in gsub.table.FeatureList.FeatureRecord} if gsub else set()


@pytest.mark.parametrize("face", FACES)
def test_every_drawn_character_the_font_has_is_in_its_subset(face: str) -> None:
    full = set(_source(face).getBestCmap())
    subset = set(_built(face).getBestCmap())
    if "italic" in face:  # covered by the italic test below
        return
    wanted = {ord(c) for c in _visible_text() | set(builder().FONT_TEXT_EXTRA)} & full
    missing = sorted(chr(c) for c in wanted - subset)
    assert not missing, f"{face} subset lacks {missing}"


def test_the_italic_mono_has_every_character_a_page_draws_in_it() -> None:
    face = "jetbrains-mono-italic-variable.woff2"
    drawn: set[str] = set()
    for path in pages():
        drawn |= builder().mono_italic_text(path.read_text(encoding="utf-8"))
    assert drawn, "no italic mono on the site: drop the face"
    full = set(_source(face).getBestCmap())
    missing = sorted(
        c for c in drawn if ord(c) in full and ord(c) not in _built(face).getBestCmap()
    )
    assert not missing, missing


def test_a_page_with_italic_mono_links_its_sheet_and_no_other_does() -> None:
    link = "/assets/css/fonts-italic.css"
    for path in pages():
        text = path.read_text(encoding="utf-8")
        assert (link in text) == bool(builder().mono_italic_text(text)), path


@pytest.mark.parametrize("face", FACES)
def test_every_face_is_cut_down_to_the_drawn_text(face: str) -> None:
    """Per face, so one unsubset face cannot hide behind the others: under half the glyphs."""
    shipped, source = len(_built(face).getBestCmap()), len(_source(face).getBestCmap())
    assert shipped * 2 < source, (face, shipped, source)


def test_the_fonts_are_inlined_and_no_font_file_is_shipped() -> None:
    """Inlined fonts arrive before the first layout; the static woff2 belong to the app image."""
    assert not list((built() / "fonts").glob("*.woff2"))
    for sheet in ("fonts.css", "fonts-italic.css"):
        assert "/fonts/" not in (built() / "assets" / "css" / sheet).read_text(encoding="utf-8")


@pytest.mark.parametrize("face", FACES)
def test_the_weight_axis_is_kept_in_the_range_the_css_uses(face: str) -> None:
    axes = (
        {a.axisTag: (a.minValue, a.maxValue) for a in _built(face)["fvar"].axes}
        if ("fvar" in _built(face))
        else {}
    )
    wanted = FACES[face][1]
    assert axes.get("wght") == (None if wanted is None else (float(wanted[0]), float(wanted[1])))


def test_the_source_fonts_stay_full() -> None:
    for face in FACES:
        font = _source(face)
        assert len(font.getBestCmap()) > 220 and "fvar" in font, face


@pytest.mark.parametrize("face", FACES)
def test_the_subset_keeps_the_features_the_site_uses(face: str) -> None:
    """tabular-nums needs `tnum`; the mono ligatures are `calt`; the default list drops `tnum`."""
    kept = _tags(_built(face))
    for tag in {"tnum"} & _tags(_source(face)):
        assert tag in kept, (face, tag)
    if face.startswith("jetbrains"):
        assert "calt" in kept, face


@pytest.mark.parametrize("face", FACES)
def test_the_stylistic_sets_nobody_asks_for_are_dropped(face: str) -> None:
    kept = _tags(_built(face))
    assert not {t for t in kept if re.fullmatch(r"(ss\d\d|cv\d\d|zero|sups|subs|sinf|ordn)", t)}, (
        face
    )


def test_only_the_weight_is_never_synthesised() -> None:
    """R13: no faux bold; an <em> in Sora (no italic face) keeps its oblique."""
    sheets = {
        p.name: p.read_text(encoding="utf-8") for p in (ROOT / "docs/assets/css").glob("*.css")
    }
    assert "html { font-synthesis-weight: none; }" in sheets["fonts.css"]
    for name, css in sheets.items():
        assert not re.search(r"font-synthesis\s*:|font-synthesis-style\s*:\s*none", css), name


def test_the_apps_static_fonts_stay_full() -> None:
    """The app image and the diagram geometry use docs/fonts as they are, never subset."""
    static_fonts = sorted((ROOT / "docs" / "fonts").glob("*.woff2"))
    assert len(static_fonts) == 6
    for path in static_fonts:
        assert len(TTFont(path).getBestCmap()) > 220, path.name


def test_a_self_closing_void_tag_does_not_end_the_italic() -> None:
    """commonmark writes `<hr />`; it was never pushed and must not pop the open <em>."""
    parse = builder().mono_italic_text
    assert parse("<pre><em>a<hr />b</em></pre>") == {"a", "b"}
    assert parse("<pre><code><em>a<br />b</em></code></pre>") == {"a", "b"}
    assert parse("<p><em>sora</em></p>") == set()


@pytest.mark.parametrize("face", FACES)
def test_the_copyright_and_license_stay_inside_the_font(face: str) -> None:
    name = _built(face)["name"]
    assert "Copyright" in (name.getDebugName(0) or ""), face
    assert "Open Font License" in (name.getDebugName(13) or ""), face

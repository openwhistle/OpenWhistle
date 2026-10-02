"""Every committed diagram is current, legible, self-contained and in its page's language.

Rendering needs a container (scripts/render_diagrams.py); these checks need nothing but
the committed files, so CI runs them on every push.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from app.models.report import ReportStatus
from tests.built_site import built, pages
from tests.diagram_tools import geometry, renderer

ROOT = Path(__file__).parents[1]
THEMES = ("light", "dark")
ALL = renderer().sources()
IDS = [source.name for source, _ in ALL]


def _svg(source: Path, out: Path, theme: str) -> str:
    return renderer().svg_path(source, out, theme).read_text(encoding="utf-8")


def test_there_are_diagrams() -> None:
    names = {s.name for s, _ in ALL}
    assert {"submission-flow.drawio", "architecture.de.drawio"} <= names, names


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_source_is_rendered_and_current(source: Path, out: Path, theme: str) -> None:
    path = renderer().svg_path(source, out, theme)
    assert path.is_file(), (
        f"{path.relative_to(ROOT)} is missing: uv run python scripts/render_diagrams.py"
    )
    m = re.search(r'data-ow-stamp="([0-9a-f]{16})"', path.read_text(encoding="utf-8"))
    assert m, f"{path.relative_to(ROOT)} has no stamp"
    assert m.group(1) == renderer().stamp(source.read_text(encoding="utf-8"), theme), (
        f"{path.relative_to(ROOT)} is stale: uv run python scripts/render_diagrams.py "
        f"{source.name.removesuffix('.drawio')}"
    )


def test_every_svg_has_a_source() -> None:
    expected = {renderer().svg_path(s, o, t) for s, o in ALL for t in THEMES}
    on_disk = {p for out in renderer().DIRS.values() if out.is_dir() for p in out.glob("*.svg")}
    orphans = sorted(p.relative_to(ROOT).as_posix() for p in on_disk - expected)
    assert not orphans, f"SVG(s) without a source, delete them: {orphans}"


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_diagram_is_legible(source: Path, out: Path, theme: str) -> None:
    roles = renderer().roles_by_id(source.read_text(encoding="utf-8"))
    found = geometry().problems(_svg(source, out, theme), roles)
    assert not found, "\n  ".join([f"{source.name} ({theme}):", *found])


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
_RGB = re.compile(r"rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)")
_BLOB = re.compile(r"base64,[A-Za-z0-9+/=]+")


def _colours(svg: str) -> set[str]:
    svg = _BLOB.sub("", svg)
    found = set()
    for h in _HEX.findall(svg):
        h = h.lower()
        found.add("#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h)
    found |= {"#{:02x}{:02x}{:02x}".format(*map(int, m)) for m in _RGB.findall(svg)}
    return found


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_colours_are_the_palette_of_their_theme(source: Path, out: Path, theme: str) -> None:
    allowed = set(renderer().palette()[theme].values())
    stray = _colours(_svg(source, out, theme)) - allowed
    assert not stray, (
        f"{source.name} ({theme}) uses {sorted(stray)}, which is not a {theme} DESIGN.md colour: "
        "a role leaves a draw.io default in place; set that key in ROLES"
    )


_NAMESPACES = {
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1999/xhtml",
}


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_svg_is_self_contained(source: Path, out: Path, theme: str) -> None:
    svg = _svg(source, out, theme)
    for marker in ("light-dark(", "<foreignObject", "<script", "<!DOCTYPE"):
        assert marker not in svg, f"{source.name} ({theme}) contains {marker}"
    assert not re.search(r"url\((?!data:)", svg), (
        f"{source.name} ({theme}) loads something by url()"
    )
    assert not re.search(r'href="(?!#|data:)', svg), f"{source.name} ({theme}) links out"
    refs = set(re.findall(r'https?://[^"\'\s)]*', svg)) - _NAMESPACES
    assert not refs, f"{source.name} ({theme}) references {sorted(refs)}"


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
def test_every_drawn_glyph_is_in_the_embedded_font(source: Path, out: Path) -> None:
    svg = _svg(source, out, "light")
    faces = {
        int(w): set(TTFont(io.BytesIO(base64.b64decode(d))).getBestCmap())
        for w, d in re.findall(r"font-weight:(\d+);src:url\(data:font/woff2;base64,([^)]+)\)", svg)
    }
    for t in geometry().texts(svg):
        missing = {c for c in t.text if ord(c) not in faces.get(t.weight, set())}
        assert not missing, (
            f"{source.name}: {t.text!r} draws {sorted(missing)} without an embedded glyph"
        )


def _diagram_srcs(html: str) -> set[str]:
    return set(re.findall(r'src="/img/diagrams/([^"]+?)-(?:light|dark)\.svg"', html))


def test_pages_show_diagrams_in_their_own_language() -> None:
    wrong = []
    for page in pages():
        html = page.read_text(encoding="utf-8")
        lang = re.search(r'<html[^>]*\blang="([a-z]{2})', html)
        for name in _diagram_srcs(html):
            german = name.endswith(".de")
            if lang and (lang.group(1) == "de") != german:
                wrong.append(f"{page.relative_to(built())} (lang={lang.group(1)}) shows {name}")
    assert not wrong, "\n  ".join(["diagram in the wrong language:", *wrong])


def test_the_case_lifecycle_names_exactly_the_report_statuses() -> None:
    source = (ROOT / "docs/_diagrams/case-lifecycle.drawio").read_text(encoding="utf-8")
    roles = renderer().roles_by_id(source)
    labels = dict(re.findall(r'<mxCell id="([^"]+)" value="([^"]*)"', source))
    steps = {labels[cid] for cid, role in roles.items() if role == "ow:step"}
    assert steps == {s.value for s in ReportStatus}

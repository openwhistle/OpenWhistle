"""Every committed diagram is current, legible, self-contained and in its page's language.

Rendering needs a container (scripts/render_diagrams.py); these checks need nothing but
the committed files, so CI runs them on every push.
"""

from __future__ import annotations

import base64
import io
import re
import subprocess
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from app.models.report import ReportStatus
from tests.built_site import built, page, pages
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


DOCS_TECH = ROOT / "docs-tech"
_OPEN = re.compile(r"^\s*(`{3,}|~{3,})\s*(\S*)")


def _split_fences(text: str) -> tuple[str, list[str]]:
    """Return (text outside fenced code, info string of every fence). CommonMark: a fence closes on
    a line of the same character, at least as long as the opening one."""
    prose, infos, fence = [], [], None
    for line in text.splitlines():
        if fence is None:
            m = _OPEN.match(line)
            if m:
                fence = m.group(1)
                infos.append(m.group(2))
            else:
                prose.append(line)
        elif re.fullmatch(rf"\s*{re.escape(fence[0])}{{{len(fence)},}}\s*", line):
            fence = None
    return "\n".join(prose), infos


def test_fences_are_split_by_commonmark_rules() -> None:
    text = (
        "a\n```text\n<picture>\n```\nb\n"
        "````md\n```mermaid\n<picture>\n```\n<picture>\n````\n"
        "  ```mermaid\nx\n  ```\nc"
    )
    prose, infos = _split_fences(text)
    assert prose == "a\nb\nc"
    assert infos == ["text", "md", "mermaid"]


def _tracked() -> list[Path]:
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines()]


def test_no_mermaid_anywhere() -> None:
    found = []
    for path in _tracked():
        if path.suffix == ".mmd":
            found.append(f"{path.relative_to(ROOT)}: a Mermaid source")
        if path.suffix in {".md", ".html"} and path.is_file() and any(
            i.lower() == "mermaid" for i in _split_fences(path.read_text(encoding="utf-8"))[1]
        ):
            found.append(f"{path.relative_to(ROOT)}: a fenced Mermaid block")
    tooling = [
        ROOT / "renovate.json", ROOT / "pyproject.toml",
        *ROOT.glob("scripts/*"), *ROOT.glob(".github/**/*.yml"),
    ]
    for path in tooling:
        if path.is_file() and re.search(
            r"mermaid-cli|@mermaid-js", path.read_text(encoding="utf-8")
        ):
            found.append(f"{path.relative_to(ROOT)}: a mermaid-cli reference")
    head = "Mermaid is gone (maintainer's decision, 2026-10-02):"
    assert not found, "\n  ".join([head, *found])


DOCS_TECH_DIAGRAMS = [(s, o) for s, o in ALL if o == DOCS_TECH / "img" / "diagrams"]


@pytest.mark.parametrize(
    ("source", "out"), DOCS_TECH_DIAGRAMS, ids=[s.name for s, _ in DOCS_TECH_DIAGRAMS]
)
def test_every_maintainer_diagram_is_embedded_as_a_picture(source: Path, out: Path) -> None:
    name = source.name.removesuffix(".drawio")
    pattern = re.compile(
        rf'<picture>\s*<source media="\(prefers-color-scheme: dark\)"'
        rf' srcset="[./]*img/diagrams/{re.escape(name)}-dark\.svg">'
        rf'\s*<img src="[./]*img/diagrams/{re.escape(name)}-light\.svg" alt="[^"]+">'
        r"\s*</picture>"
    )
    hits = [
        p for p in DOCS_TECH.rglob("*.md")
        if pattern.search(_split_fences(p.read_text(encoding="utf-8"))[0])
    ]
    assert hits, f"no page in docs-tech/ shows {name} as a <picture> with both themes and alt text"
    for page_file in hits:
        prose = _split_fences(page_file.read_text(encoding="utf-8"))[0]
        found = re.search(rf'src="([^"]*{re.escape(name)}-light\.svg)"', prose)
        assert found, f"{page_file}: no src for {name}-light.svg outside code blocks"
        target = page_file.parent / found.group(1)
        want = (out / f"{name}-light.svg").resolve()
        assert target.resolve() == want, f"{page_file}: wrong relative path"


def _diagram_srcs(html: str) -> set[str]:
    return set(re.findall(r'src="/img/diagrams/([^"]+?)-(?:light|dark)\.svg"', html))


def test_pages_show_diagrams_in_their_own_language() -> None:
    wrong = []
    for path in pages():
        html = path.read_text(encoding="utf-8")
        lang = re.search(r'<html[^>]*\blang="([a-z]{2})', html)
        for name in _diagram_srcs(html):
            german = name.endswith(".de")
            if lang and (lang.group(1) == "de") != german:
                wrong.append(f"{path.relative_to(built())} (lang={lang.group(1)}) shows {name}")
    assert not wrong, "\n  ".join(["diagram in the wrong language:", *wrong])


def test_the_case_lifecycle_names_exactly_the_report_statuses() -> None:
    source = (ROOT / "docs/_diagrams/case-lifecycle.drawio").read_text(encoding="utf-8")
    roles = renderer().roles_by_id(source)
    labels = dict(re.findall(r'<mxCell id="([^"]+)" value="([^"]*)"', source))
    steps = {labels[cid] for cid, role in roles.items() if role == "ow:step"}
    assert steps == {s.value for s in ReportStatus}


@pytest.mark.parametrize(("url", "name"), [("/en/", "home-flow"), ("/de/", "home-flow.de")])
def test_the_home_page_shows_the_reporting_flow_as_a_diagram(url: str, name: str) -> None:
    html = page(url)
    assert name in _diagram_srcs(html), f"{url} does not show {name}"
    assert "flows-grid" not in html, f"{url} still carries the HTML flow next to the diagram"

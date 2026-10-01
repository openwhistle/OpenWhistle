"""Every diagram and screenshot is shown somewhere, in both themes, and every
image says what it shows.

A committed picture no page references is either stale or forgotten, and it
is easy to lose one in a rewrite: the render and screenshot scripts keep
producing it whether or not anyone embeds it. A picture with only its light
twin in the markup leaves dark-theme readers without it. And an ``<img>``
without alt text gives a screen reader, or anyone whose image failed to load,
nothing at all.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
FIGURE_DIRS = ("img/screens", "img/diagrams")


class _Images(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.images.append(dict(attrs))


def _images(page: Path) -> list[dict[str, str | None]]:
    parser = _Images()
    parser.feed(page.read_text(encoding="utf-8"))
    return parser.images


def _pages() -> list[Path]:
    return sorted(p for p in DOCS.rglob("*.html") if "/docs/_" not in p.as_posix())


def _srcs() -> set[str]:
    """Every <img src> of every published page, resolved relative to docs/."""
    found: set[str] = set()
    for page in _pages():
        for img in _images(page):
            src = img.get("src") or ""
            if src and "://" not in src and not src.startswith("data:"):
                found.add((page.parent / src).resolve().relative_to(DOCS.resolve()).as_posix())
    return found


def _light_figures() -> list[str]:
    return sorted(
        p.relative_to(DOCS).as_posix()
        for d in FIGURE_DIRS
        for p in (DOCS / d).iterdir()
        if re.search(r"-light\.(png|svg)$", p.name)
    )


def test_there_are_figures_to_check() -> None:
    names = _light_figures()
    assert any(n.startswith("img/screens/") for n in names), "no screenshot found"
    assert any(n.startswith("img/diagrams/") for n in names), "no diagram found"


@pytest.mark.parametrize("light", _light_figures())
def test_every_figure_is_embedded_with_its_dark_twin(light: str) -> None:
    srcs = _srcs()
    dark = light.replace("-light.", "-dark.")
    assert light in srcs, f"{light} is on disk but no page under docs/ shows it"
    assert (DOCS / dark).is_file(), f"{light} has no dark twin {dark}"
    assert dark in srcs, f"{light} is embedded without its dark twin {dark}"


def test_every_embedded_image_exists() -> None:
    missing = sorted(src for src in _srcs() if not (DOCS / src).is_file())
    assert not missing, f"page(s) under docs/ point at image(s) that do not exist: {missing}"


def _unlabelled(page: Path) -> list[str]:
    return [
        str(img.get("src"))
        for img in _images(page)
        if img.get("aria-hidden") != "true" and not (img.get("alt") or "").strip()
    ]


def test_every_image_has_alt_text_unless_hidden() -> None:
    bare = [f"{page.relative_to(ROOT)}: {src}" for page in _pages() for src in _unlabelled(page)]
    assert not bare, "image(s) without alt text:\n  " + "\n  ".join(bare)


def test_the_alt_rule_is_pinned(tmp_path: Path) -> None:
    page = tmp_path / "p.html"
    page.write_text(
        '<img src="a.png" alt="A chart"><img src="b.png" alt=" "><img src="c.png">'
        '<img src="d.png" aria-hidden="true" alt="">'
    )
    assert _unlabelled(page) == ["b.png", "c.png"]

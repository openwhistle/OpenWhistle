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

from tests.built_site import built, pages

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


def _srcs() -> set[str]:
    """Every <img src> of every built page, resolved relative to the site root."""
    site = built().resolve()
    found: set[str] = set()
    for page in pages():
        for img in _images(page):
            src = img.get("src") or ""
            if src and "://" not in src and not src.startswith("data:"):
                target = site / src.lstrip("/") if src.startswith("/") else page.parent / src
                found.add(target.resolve().relative_to(site).as_posix())
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
    assert light in srcs, f"{light} is on disk but no built page shows it"
    assert (DOCS / dark).is_file(), f"{light} has no dark twin {dark}"
    assert dark in srcs, f"{light} is embedded without its dark twin {dark}"


def test_every_embedded_image_exists() -> None:
    missing = sorted(src for src in _srcs() if not (built() / src).is_file())
    assert not missing, f"built page(s) point at image(s) that do not exist: {missing}"


def _unlabelled(page: Path) -> list[str]:
    return [
        str(img.get("src"))
        for img in _images(page)
        if img.get("aria-hidden") != "true" and not (img.get("alt") or "").strip()
    ]


def test_every_image_has_alt_text_unless_hidden() -> None:
    bare = [f"{page.relative_to(built())}: {src}" for page in pages() for src in _unlabelled(page)]
    assert not bare, "image(s) without alt text:\n  " + "\n  ".join(bare)


def test_the_alt_rule_is_pinned(tmp_path: Path) -> None:
    page = tmp_path / "p.html"
    page.write_text(
        '<img src="a.png" alt="A chart"><img src="b.png" alt=" "><img src="c.png">'
        '<img src="d.png" aria-hidden="true" alt="">'
    )
    assert _unlabelled(page) == ["b.png", "c.png"]


def _natural_size(path: Path) -> tuple[float, float]:
    if path.suffix == ".svg":
        root = re.search(r"<svg\b[^>]*>", path.read_text(encoding="utf-8"))
        assert root, path
        w, h = (re.search(rf'\b{a}="([\d.]+)"', root.group(0)) for a in ("width", "height"))
        assert w and h, f"{path}: the <svg> has no width/height"
        return float(w.group(1)), float(h.group(1))
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def test_every_image_reserves_its_real_shape() -> None:
    """width/height set the box before a lazy image loads; a wrong ratio shifts
    everything below it when it arrives, and a #deep-link lands off its section."""
    site = built().resolve()
    wrong = []
    for page in pages():
        for img in _images(page):
            src, width, height = img.get("src") or "", img.get("width"), img.get("height")
            if not (width and height) or "://" in src or src.startswith("data:"):
                continue
            file = site / src.lstrip("/") if src.startswith("/") else page.parent / src
            nw, nh = _natural_size(file)
            if abs(int(width) / int(height) - nw / nh) > 0.01:
                wrong.append(
                    f"{page.relative_to(site)}: {src} is {width}x{height}, the file {nw:g}x{nh:g}"
                )
    assert not wrong, "\n  ".join(["width/height disagree with the file:", *sorted(set(wrong))])


@pytest.mark.parametrize(
    "url",
    [
        "/en/",
        "/de/",
        "/en/docs/",
        "/en/blog/free-internal-reporting-channel/",
        "/de/blog/interne-meldestelle-kostenlos/",
    ],
)
def test_a_diagram_scrolls_inside_its_figure_on_a_phone(url: str) -> None:
    from tests.built_site import page

    hrefs = re.findall(r'<link[^>]+href="(/assets/css/[^"]+\.css)"', page(url))
    css = "".join((built() / h.lstrip("/")).read_text(encoding="utf-8") for h in hrefs)
    narrow = r"@media \(max-width: 6\d\dpx\) \{[^{}]*\.diagram \{[^}]*overflow-x: auto"
    rule = re.search(narrow, css)
    assert rule, f"{url}: no narrow-width rule gives .diagram overflow-x: auto"

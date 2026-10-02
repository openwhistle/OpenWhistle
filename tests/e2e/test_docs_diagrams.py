"""Every diagram on the site, as the browser lays it out: one twin per theme, at its size.

A stylesheet diff cannot show which of two images a cascade hides, or how wide a grid
column draws an SVG; only a browser can. The page list comes from the built site, so a
new page with a diagram is checked without anyone adding it here.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, Page

from tests.built_site import built, pages

pytestmark = pytest.mark.e2e

URLS = sorted(
    "/" + p.relative_to(built()).as_posix().removesuffix("index.html")
    for p in pages()
    if re.search(r'<figure class="diagram\b', p.read_text(encoding="utf-8"))
)
MIN_SCALE = 0.85  # below it a 13 px label drops under 11 px

# Per figure: [class, rendered width, width attribute] of every displayed image.
_SHOWN = """() => [...document.querySelectorAll('figure.diagram')].map(f =>
  [...f.querySelectorAll('img')].filter(i => getComputedStyle(i).display !== 'none')
    .map(i => [i.className, i.getBoundingClientRect().width, Number(i.getAttribute('width'))]))"""
_LOAD_ALL = """() => Promise.all([...document.querySelectorAll('figure.diagram img')].map(i => {
  i.loading = 'eager';
  return i.complete ? null : new Promise(r => { i.onload = i.onerror = r; });
}))"""


def _open(browser: Browser, url: str, width: int, scheme: str = "dark") -> Page:
    ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)
    page = ctx.new_page()
    page.goto(url)
    # loading="lazy" leaves an image below the fold unloaded, and an unloaded image with
    # width: auto measures 0: load them all, so the layout is the one a reader scrolls to.
    page.evaluate(_LOAD_ALL)
    return page


def test_diagram_pages_are_found() -> None:
    assert {"/en/", "/de/", "/en/docs/"} <= set(URLS), URLS


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("url", URLS)
def test_each_figure_shows_exactly_its_themes_twin(
    browser: Browser, docs_server_url: str, url: str, theme: str
) -> None:
    page = _open(browser, docs_server_url + url, 1440, theme)
    assert page.evaluate("document.documentElement.dataset.theme") == theme
    shown = page.evaluate(_SHOWN)
    page.context.close()
    wrong = [s for s in shown if [c for c, _, _ in s] != [f"diagram-{theme}"]]
    assert not wrong, f"{url} ({theme}): figures showing {wrong}"


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("url", URLS)
def test_each_diagram_sits_on_the_canvas(
    browser: Browser, docs_server_url: str, url: str, theme: str
) -> None:
    """A diagram's cards are surface; on a surface section without the canvas they vanish."""
    page = _open(browser, docs_server_url + url, 1440, theme)
    canvas, *grounds = page.evaluate(
        "() => [getComputedStyle(document.body).backgroundColor, ...[...document.querySelectorAll("
        "'figure.diagram img')].map(i => getComputedStyle(i).backgroundColor)]"
    )
    page.context.close()
    assert set(grounds) == {canvas}, f"{url} ({theme}): diagrams on {grounds}, not on {canvas}"


@pytest.mark.parametrize("width", [1280, 1440, 1920])
@pytest.mark.parametrize("url", URLS)
def test_each_diagram_renders_near_its_size_on_a_desktop(
    browser: Browser, docs_server_url: str, url: str, width: int
) -> None:
    page = _open(browser, docs_server_url + url, width)
    shown = page.evaluate(_SHOWN)
    page.context.close()
    off = [
        f"{c}: {w:.0f} of {n} px ({w / n:.2f})"
        for s in shown
        for c, w, n in s
        if not MIN_SCALE <= w / n <= 1.0 + 1e-3
    ]
    assert not off, f"{url} at {width} px: diagrams outside {MIN_SCALE}-1.00 of their size: {off}"


@pytest.mark.parametrize("url", URLS)
def test_on_a_phone_a_diagram_keeps_its_size_and_the_page_does_not_scroll_sideways(
    browser: Browser, docs_server_url: str, url: str
) -> None:
    page = _open(browser, docs_server_url + url, 390)
    scroll = page.evaluate("document.documentElement.scrollWidth")
    shown = page.evaluate(_SHOWN)
    page.context.close()
    assert scroll <= 390, f"{url}: the page is {scroll} px wide at 390 px"
    shrunk = [f"{c}: {w:.0f} of {n} px" for s in shown for c, w, n in s if abs(w - n) > 0.5]
    assert not shrunk, f"{url} at 390 px: diagrams not at their size: {shrunk}"

"""What the built site looks like in a browser: computed values a static scan cannot see."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser

from tests.built_site import built, pages

pytestmark = pytest.mark.e2e


def test_the_preloaded_fonts_are_the_ones_the_first_view_uses(
    browser: Browser, docs_server_url: str
) -> None:
    used: set[str] = set()
    preloaded: set[str] = set()
    for width in (1920, 390):
        for url in ("/en/", "/de/"):
            ctx = browser.new_context(viewport={"width": width, "height": 900})
            try:
                page = ctx.new_page()
                page.goto(f"{docs_server_url}{url}")
                page.evaluate("document.fonts.ready")
                used |= set(
                    page.evaluate(
                        """() => { const out = new Set();
                     for (const el of document.querySelectorAll('body *')) {
                       const r = el.getBoundingClientRect();
                       if (r.bottom <= 0 || r.top >= innerHeight || !el.childNodes.length) continue;
                       if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))
                         continue;
                       const cs = getComputedStyle(el);
                       if (cs.visibility === 'hidden' || cs.display === 'none') continue;
                       const fam = cs.fontFamily.split(',')[0].replace(/['"]/g, '').trim();
                       const it = cs.fontStyle === 'italic' ? ' italic' : '';
                       out.add(fam + ' ' + cs.fontWeight + it);
                     }
                     return [...out]; }"""
                    )
                )
                preloaded |= set(
                    page.evaluate(
                        "() => [...document.querySelectorAll('link[rel=preload][as=font]')]"
                        ".map(l => l.href.split('/').pop())"
                    )
                )
            finally:
                ctx.close()
    sora = {u.split()[1] for u in used if u.startswith("Sora ") and "italic" not in u}
    matches = (re.search(r"sora-latin-(\d+)-normal", f) for f in preloaded)
    found = {m.group(1) for m in matches if m}
    assert found == sora, (sorted(sora), sorted(found))


@pytest.mark.parametrize("theme,expected", [("light", "light only"), ("dark", "dark")])
def test_the_page_declares_its_scheme(
    browser: Browser, docs_server_url: str, theme: str, expected: str
) -> None:
    ctx = browser.new_context(color_scheme="dark")
    ctx.add_init_script(f"localStorage.setItem('ow-theme','{theme}')")
    try:
        page = ctx.new_page()
        page.goto(f"{docs_server_url}/en/")
        assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == expected
    finally:
        ctx.close()


STEPS_POSTS = (
    "/en/blog/set-up-internal-reporting-channel/",
    "/de/blog/interne-meldestelle-einrichten/",
)


@pytest.mark.parametrize("url", STEPS_POSTS)
@pytest.mark.parametrize("width", [1920, 768])
def test_a_path_in_a_deadline_table_stays_on_one_line(
    browser: Browser, docs_server_url: str, url: str, width: int
) -> None:
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    try:
        page = ctx.new_page()
        page.goto(f"{docs_server_url}{url}")
        page.evaluate("document.fonts.ready")
        broken = page.evaluate(
            "() => [...document.querySelectorAll('.deadline-table code')]"
            ".filter(c => c.getClientRects().length !== 1).map(c => c.textContent)"
        )
    finally:
        ctx.close()
    assert broken == [], f"{url} at {width} px: code broken over lines: {broken}"


def test_reduced_motion_stops_the_reveal_and_the_smooth_scroll(
    browser: Browser, docs_server_url: str
) -> None:
    ctx = browser.new_context(reduced_motion="reduce")
    try:
        page = ctx.new_page()
        page.goto(f"{docs_server_url}/en/")
        duration = page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('.hero-headline')).animationDuration)"
        )
        scroll = page.evaluate("getComputedStyle(document.documentElement).scrollBehavior")
    finally:
        ctx.close()
    assert duration < 0.001, duration  # seconds
    assert scroll == "auto", scroll


URLS = sorted("/" + p.relative_to(built()).as_posix().removesuffix("index.html") for p in pages())


@pytest.mark.parametrize("url", URLS)
def test_no_page_is_wider_than_a_small_phone(
    browser: Browser, docs_server_url: str, url: str
) -> None:
    ctx = browser.new_context(viewport={"width": 360, "height": 800})
    try:
        page = ctx.new_page()
        page.goto(f"{docs_server_url}{url}")
        page.evaluate("document.fonts.ready")
        width = page.evaluate("document.documentElement.scrollWidth")
    finally:
        ctx.close()
    assert width <= 360, f"{url} is {width} px wide at 360 px"

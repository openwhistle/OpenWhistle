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
def test_a_path_in_a_data_table_stays_on_one_line(
    browser: Browser, docs_server_url: str, url: str, width: int
) -> None:
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    try:
        page = ctx.new_page()
        page.goto(f"{docs_server_url}{url}")
        page.evaluate("document.fonts.ready")
        broken = page.evaluate(
            "() => [...document.querySelectorAll('.data-table code')]"
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


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_nav_mark_reads_against_the_nav(
    browser: Browser, docs_server_url: str, theme: str
) -> None:
    ctx = browser.new_context()
    try:
        ctx.add_init_script(f"localStorage.setItem('ow-theme','{theme}')")
        page = ctx.new_page()
        page.goto(f"{docs_server_url}/en/")
        fill, ink, bg = page.evaluate(
            """() => { const m = document.querySelector('.site-nav .mark path');
                       const n = document.querySelector('.site-nav');
                       return [getComputedStyle(m).fill,
                               getComputedStyle(document.querySelector('.nav-logo')).color,
                               getComputedStyle(n).backgroundColor]; }"""
        )
    finally:
        ctx.close()
    # The mark takes the wordmark's ink (currentColor), and that ink is not the nav's ground.
    assert fill == ink and fill != bg and fill not in ("none", "rgba(0, 0, 0, 0)"), (
        theme,
        fill,
        ink,
        bg,
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_footer_mark_reads_at_half_emphasis(
    browser: Browser, docs_server_url: str, theme: str
) -> None:
    ctx = browser.new_context()
    try:
        ctx.add_init_script(f"localStorage.setItem('ow-theme','{theme}')")
        page = ctx.new_page()
        page.goto(f"{docs_server_url}/en/")
        fill, opacity, bg = page.evaluate(
            """() => { const m = document.querySelector('.footer-logo .mark');
                       return [getComputedStyle(m.querySelector('path')).fill,
                               getComputedStyle(m).opacity,
                               getComputedStyle(document.querySelector('.site-footer'))
                                 .backgroundColor]; }"""
        )
    finally:
        ctx.close()
    # The old shield's look: footer ink at half emphasis (.footer-logo .mark in base.css).
    assert fill != bg and fill not in ("none", "rgba(0, 0, 0, 0)"), (theme, fill, bg)
    assert opacity == "0.5", (theme, opacity)


@pytest.mark.parametrize("url", URLS)
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_code_block_draws_no_inline_code_pill(
    browser: Browser, docs_server_url: str, theme: str, url: str
) -> None:
    """The inline-code pill stops at a code block, on every page: dark mode once painted a grey
    box per line, and a bare <pre><code> in the docs still did."""
    ctx = browser.new_context()
    try:
        ctx.add_init_script(f"localStorage.setItem('ow-theme','{theme}')")
        page = ctx.new_page()
        page.goto(f"{docs_server_url}{url}")
        pills = page.evaluate(
            """() => [...document.querySelectorAll('pre code')]
                     .map(c => getComputedStyle(c))
                     .filter(s => s.backgroundColor !== 'rgba(0, 0, 0, 0)'
                                  || s.boxShadow !== 'none' || s.paddingLeft !== '0px')
                     .length"""
        )
    finally:
        ctx.close()
    assert pills == 0, (theme, url, pills)


PROSE_PAGES = ("/en/docs/", "/en/blog/hinschg-compliance-guide/", "/en/roadmap/")


@pytest.mark.parametrize("url", PROSE_PAGES)
def test_prose_lines_stay_near_seventy_characters(
    browser: Browser, docs_server_url: str, url: str
) -> None:
    """DESIGN.md "Rules": a paragraph is at most ~70 characters wide (width / width of "0")."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    try:
        page = ctx.new_page()
        page.goto(f"{docs_server_url}{url}")
        page.evaluate("document.fonts.ready")
        widest = page.evaluate(
            """() => { let worst = [0, ''];
              for (const p of document.querySelectorAll(
                  'main p, .docs-section p, .article-body p, .docs-content p')) {
                const cs = getComputedStyle(p);
                if (parseFloat(cs.fontSize) < 14) continue; // eyebrows and tags are not prose
                const probe = document.createElement('span');
                probe.style.cssText = 'position:absolute;visibility:hidden;width:100ch';
                p.appendChild(probe);
                const ch = probe.getBoundingClientRect().width / 100;
                probe.remove();
                const w = p.getBoundingClientRect().width
                  - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
                if (w / ch > worst[0]) worst = [w / ch, p.textContent.trim().slice(0, 40)];
              }
              return worst; }"""
        )
    finally:
        ctx.close()
    assert 0 < widest[0] <= 72, (url, widest)


@pytest.mark.parametrize("url", ["/en/", "/en/docs/", "/en/compare/", "/en/roadmap/"])
def test_a_rounded_child_in_a_tight_rounded_parent_is_concentric(
    browser: Browser, docs_server_url: str, url: str
) -> None:
    """DESIGN.md "Rules": inner radius = outer radius - padding while the padding is below it."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    try:
        page = ctx.new_page()
        page.goto(f"{docs_server_url}{url}")
        bad = page.evaluate(
            """() => { const out = [], px = v => parseFloat(v) || 0;
              for (const el of document.querySelectorAll('body *')) {
                const p = el.parentElement, c = getComputedStyle(el), s = getComputedStyle(p);
                const ro = px(s.borderTopLeftRadius), ri = px(c.borderTopLeftRadius);
                if (!ro || !ri || ro > 500 || ri > 500) continue;
                const gap = Math.min(px(s.paddingTop), px(s.paddingLeft));
                if (gap < ro && ri > ro - gap + 0.5)
                  out.push(`${el.tagName}.${el.className} ${ri} in ${p.className} ${ro}/${gap}`);
              }
              return out; }"""
        )
    finally:
        ctx.close()
    assert not bad, bad

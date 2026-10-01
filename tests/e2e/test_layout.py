"""Layout rules that only a real browser can measure."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser

from tests.e2e.conftest import (
    _DOCS_DIR,
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    _admin_login,
)

pytestmark = pytest.mark.e2e

_DOCS_PAGES = sorted(
    str(p.relative_to(_DOCS_DIR))
    for p in _DOCS_DIR.rglob("*.html")
    if "/docs/_" not in p.as_posix()
)

# Every page of the published site, found by glob so a new page is covered
# the day it is added. Nine pages exist today; a glob that suddenly finds
# fewer means the directory moved, not that the site shrank.
_DOCS_PAGE_FLOOR = 9


def test_docs_page_glob_finds_every_page() -> None:
    assert len(_DOCS_PAGES) >= _DOCS_PAGE_FLOOR, _DOCS_PAGES


# `docs_server_url` (module-scoped: serves docs/ over HTTP) lives in
# tests/e2e/conftest.py, shared with test_docs_behaviour.py.


# 390 px is a phone; 1024 px is the narrowest desktop width, where the full
# nav row has the least room before it collapses at 1080 px. Both themes: the
# first round of this check only ever ran with the browser's default (light)
# colour scheme, so a dark-only overflow (a token that only widens under
# [data-theme="dark"]) had no test to catch it.
@pytest.mark.parametrize("color_scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [390, 1024])
@pytest.mark.parametrize("docs_page", _DOCS_PAGES)
def test_docs_page_has_no_horizontal_overflow(
    browser: Browser, docs_server_url: str, docs_page: str, width: int, color_scheme: str
) -> None:
    ctx, page = _page(browser, docs_server_url, width, color_scheme=color_scheme)
    page.goto(f"{docs_server_url}/{docs_page}")
    page.wait_for_load_state("networkidle")
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    ctx.close()
    assert overflow == 0, (
        f"{docs_page}: {overflow}px horizontal overflow at {width}px ({color_scheme})"
    )


_WIDE_TABLE_PAGES = [p for p in _DOCS_PAGES if "comp-wrap" in (_DOCS_DIR / p).read_text()]


@pytest.mark.parametrize("width", [1440, 1920])
@pytest.mark.parametrize("docs_page", _WIDE_TABLE_PAGES)
def test_a_wide_table_is_centred_on_the_text_column(
    browser: Browser, docs_server_url: str, docs_page: str, width: int
) -> None:
    """A table that breaks out of the 70ch prose column stays centred on it.
    Its width was capped at 100ch while its left edge was computed from the
    full window, so on a wide screen it sat flush with the window's left edge."""
    ctx, page = _page(browser, docs_server_url, width)
    page.goto(f"{docs_server_url}/{docs_page}")
    offsets = page.evaluate(
        """() => {
            const prose = [...document.querySelectorAll('article p, main p')]
                .find(p => p.getBoundingClientRect().width > 300).getBoundingClientRect();
            const centre = r => (r.left + r.right) / 2;
            return [...document.querySelectorAll('.comp-wrap')]
                .map(w => Math.round(centre(w.getBoundingClientRect()) - centre(prose)));
        }"""
    )
    ctx.close()
    assert offsets, f"{docs_page}: no wide table"
    assert all(abs(o) <= 2 for o in offsets), f"{docs_page}@{width}px: off centre by {offsets}px"


def _page(browser: Browser, base_url: str, width: int, color_scheme: str = "light"):  # type: ignore[no-untyped-def]
    # The docs pages' own inline script falls back to `prefers-color-scheme`
    # when no `ow-theme` was ever saved in this (fresh) context's localStorage,
    # so setting the context's colour scheme is enough to render dark mode —
    # no cookie or script injection needed.
    ctx = browser.new_context(
        viewport={"width": width, "height": 900}, base_url=base_url, color_scheme=color_scheme
    )
    return ctx, ctx.new_page()


def test_admin_nav_links_never_wrap_on_desktop(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    heights = page.eval_on_selector_all(
        ".admin-nav a", "els => els.map(e => e.getBoundingClientRect().height)"
    )
    assert heights and max(heights) < 48, heights
    assert page.locator(".nav").bounding_box()["height"] <= 72  # type: ignore[index]
    ctx.close()


def test_admin_menu_is_closed_on_a_phone(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    assert page.eval_on_selector("#admin-menu", "d => d.open") is False
    assert page.locator(".nav").bounding_box()["height"] <= 72  # type: ignore[index]
    page.click(".admin-menu-toggle")
    assert page.locator(".admin-nav a[href='/admin/dashboard']").is_visible()
    ctx.close()


def test_demo_banner_is_one_line_on_a_phone(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    page.goto("/submit")
    assert page.locator(".demo-banner").bounding_box()["height"] <= 56  # type: ignore[index]
    theme = page.locator("#theme-toggle").bounding_box()
    brand = page.locator(".nav-brand").bounding_box()
    assert theme and brand and abs(theme["y"] - brand["y"]) < 24  # same row as the brand
    ctx.close()


def test_footer_links_share_one_row_and_brand_outshines_tagline(
    browser: Browser, base_url: str
) -> None:
    ctx, page = _page(browser, base_url, 1440)
    page.goto("/submit")
    ys = page.eval_on_selector_all(
        ".footer-links li", "els => els.map(e => e.getBoundingClientRect().y)"
    )
    assert ys and max(ys) - min(ys) < 4, ys  # one row, not stacked

    def _brightness(selector: str) -> float:
        color = page.eval_on_selector(selector, "e => getComputedStyle(e).color")
        return sum(float(n) for n in color.strip("rgba()").split(",")[:3])

    assert _brightness(".footer-brand") > _brightness(".footer-tagline")
    ctx.close()


def test_report_form_is_on_the_first_phone_screen(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    page.goto("/submit")
    top = page.locator("form[action='/submit']").bounding_box()
    assert top and top["y"] < 600, top
    ctx.close()


def test_case_number_stays_on_one_line(browser: Browser, base_url: str) -> None:
    from tests.e2e.conftest import DEMO_CASE_PENDING

    ctx, page = _page(browser, base_url, 390)
    page.goto("/status")
    page.fill('input[name="case_number"]', DEMO_CASE_PENDING["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_PENDING["pin"])
    page.click("button.btn-primary[type='submit']")
    token = page.locator(".token").first
    box = token.bounding_box()
    line = float(token.evaluate("e => parseFloat(getComputedStyle(e).lineHeight)"))
    assert box and box["height"] < line * 1.5
    ctx.close()


def test_stats_panels_share_the_same_top(browser: Browser, base_url: str) -> None:
    """`.panel + .panel` (site.css) adds a stacking
    margin meant for panels in normal vertical flow; inside the stats page's
    two-column grid it also fired, pushing "nach Kategorie" 23px below "nach
    Status" even though the grid's own `gap` already spaces them."""
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    page.goto(f"{base_url}/admin/stats")
    page.wait_for_load_state("networkidle")
    tops = page.eval_on_selector_all(
        ".stat-two-col > .panel", "els => els.map(e => e.getBoundingClientRect().y)"
    )
    assert len(tops) >= 2, tops
    assert max(tops) - min(tops) < 2, tops
    ctx.close()


def test_status_is_visible_in_the_phone_table(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    badge = page.locator(".table-stack .stack-status .badge").first.bounding_box()
    assert badge and badge["x"] + badge["width"] <= 390
    ctx.close()


@pytest.mark.parametrize("path", ["/", "/status", "/admin/login"])
def test_a_page_that_fits_does_not_scroll_with_the_demo_banner(
    browser: Browser, base_url: str, path: str
) -> None:
    """The e2e stack runs in demo mode, so the banner is on every page. On a
    screen tall enough for the content, the footer ends flush with the window:
    no scrollbar, nothing below the fold."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 1400}, base_url=base_url)
    page = ctx.new_page()
    page.goto(path)
    assert page.locator(".demo-banner").is_visible()
    heights = page.evaluate(
        "[document.documentElement.scrollHeight, innerHeight,"
        " Math.round(document.querySelector('footer').getBoundingClientRect().bottom)]"
    )
    ctx.close()
    assert heights[0] == heights[1] == heights[2], heights


def test_the_wizard_sidebar_does_not_set_the_page_height(browser: Browser, base_url: str) -> None:
    """The sidebar's text is longer than the form (German: 1,023 px in a 300 px
    column). In two columns it takes the height of the row and scrolls inside
    itself, so the page is as tall as the form, not as tall as the sidebar."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 700}, base_url=base_url)
    page = ctx.new_page()
    page.goto("/submit")
    sidebar, form = page.evaluate(
        "[document.querySelector('.split-sidebar'), document.querySelector('.split-main')]"
        ".map(e => [Math.round(e.getBoundingClientRect().height), e.scrollHeight])"
    )
    ctx.close()
    assert sidebar[0] == form[0], (sidebar, form)
    assert sidebar[1] > sidebar[0], "sidebar fits at 700 px: the overflow is not exercised"


def test_the_demo_credentials_sit_beside_the_login_form(browser: Browser, base_url: str) -> None:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=base_url)
    page = ctx.new_page()
    page.goto("/admin/login")
    box = page.locator(".demo-credentials").bounding_box()
    form = page.locator("form[action='/admin/login']").bounding_box()
    ctx.close()
    assert box and form
    assert box["x"] >= form["x"] + form["width"], (box, form)
    assert box["y"] < form["y"] + form["height"], (box, form)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_the_wizard_first_step_fits_a_full_hd_window(
    browser: Browser, base_url: str, lang: str
) -> None:
    """1920 x 890 is a Full HD screen minus the browser's own chrome. The first
    step, with the demo banner, ends flush with it: no scrollbar, footer in view."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 890}, base_url=base_url)
    page = ctx.new_page()
    page.goto(f"/submit?lang={lang}")
    heights = page.evaluate("[document.documentElement.scrollHeight, innerHeight]")
    ctx.close()
    assert heights[0] == heights[1], heights


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("width", [390, 1440])
def test_status_steps_neither_touch_nor_get_cut(
    browser: Browser, base_url: str, width: int, lang: str
) -> None:
    """German has the longest step labels. They ran into one another with no
    gap ("EINGEGANGENIN PRÜFUNG…") and the last was cut: labels never wrapped,
    so the lines between them shrank to nothing and overflow: hidden clipped."""
    from tests.e2e.conftest import DEMO_CASE_RECEIVED

    ctx = browser.new_context(
        viewport={"width": width, "height": 900}, base_url=base_url,
        extra_http_headers={"Accept-Language": lang},
    )
    page = ctx.new_page()
    page.goto("/status")
    page.fill('input[name="case_number"]', DEMO_CASE_RECEIVED["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_RECEIVED["pin"])
    page.click("button.btn-primary[type='submit']")
    boxes = page.eval_on_selector_all(
        ".stepper-label",
        "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.left, r.right]; })",
    )
    stepper = page.locator(".stepper").bounding_box()
    ctx.close()
    assert len(boxes) == 4 and stepper, boxes
    for (_, right), (left, _) in zip(boxes, boxes[1:], strict=False):
        assert left - right >= 4, boxes
    assert boxes[0][0] >= stepper["x"] - 0.5, (boxes, stepper)
    assert boxes[-1][1] <= stepper["x"] + stepper["width"] + 0.5, (boxes, stepper)

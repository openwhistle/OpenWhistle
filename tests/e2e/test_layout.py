"""Layout rules that only a real browser can measure."""

from __future__ import annotations

import http.server
import threading
from collections.abc import Generator
from functools import partial
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    _admin_login,
)

pytestmark = pytest.mark.e2e

# The static marketing/docs site (docs/) ships no server of its own — it is
# published as GitHub Pages. Serve it locally so the 390px overflow check
# below runs standalone, without the FastAPI app or the review stack.
_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"
_DOCS_PAGES = sorted(str(p.relative_to(_DOCS_DIR)) for p in _DOCS_DIR.rglob("*.html"))

# Every page of the published site, found by glob so a new page is covered
# the day it is added. Nine pages exist today; a glob that suddenly finds
# fewer means the directory moved, not that the site shrank.
_DOCS_PAGE_FLOOR = 9


def test_docs_page_glob_finds_every_page() -> None:
    assert len(_DOCS_PAGES) >= _DOCS_PAGE_FLOOR, _DOCS_PAGES


@pytest.fixture(scope="module")
def docs_server_url() -> Generator[str]:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(_DOCS_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


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

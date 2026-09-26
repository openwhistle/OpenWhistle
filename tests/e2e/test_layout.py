"""Layout findings of the v1.5.0 assessment, measured in a real browser."""

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

# docs/de/index.html is being rebuilt in the current design by task X11
# (including its 390px overflow); remove this xfail once that lands.
_KNOWN_OVERFLOW = {"de/index.html"}


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


@pytest.mark.parametrize(
    "docs_page",
    [
        pytest.param(
            p,
            marks=pytest.mark.xfail(
                strict=True,
                reason="X11 rebuilds docs/de/index.html in the current design, "
                "including this overflow — remove this xfail once it lands",
            ),
        )
        if p in _KNOWN_OVERFLOW
        else p
        for p in _DOCS_PAGES
    ],
)
def test_docs_page_has_no_horizontal_overflow_on_a_phone(
    browser: Browser, docs_server_url: str, docs_page: str
) -> None:
    ctx, page = _page(browser, docs_server_url, 390)
    page.goto(f"{docs_server_url}/{docs_page}")
    page.wait_for_load_state("networkidle")
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    ctx.close()
    assert overflow == 0, f"{docs_page}: {overflow}px horizontal overflow at 390px"


def _page(browser: Browser, base_url: str, width: int):  # type: ignore[no-untyped-def]
    ctx = browser.new_context(viewport={"width": width, "height": 900}, base_url=base_url)
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


def test_status_is_visible_in_the_phone_table(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    badge = page.locator(".table-stack .stack-status .badge").first.bounding_box()
    assert badge and badge["x"] + badge["width"] <= 390
    ctx.close()

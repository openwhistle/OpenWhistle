"""Layout findings of the v1.5.0 assessment, measured in a real browser."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    _admin_login,
)

pytestmark = pytest.mark.e2e


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


def test_footer_links_share_one_row_and_brand_outshines_tagline(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 1440)
    page.goto("/submit")
    ys = page.eval_on_selector_all(".footer-links li", "els => els.map(e => e.getBoundingClientRect().y)")
    assert ys and max(ys) - min(ys) < 4, ys  # one row, not stacked

    def _brightness(selector: str) -> float:
        color = page.eval_on_selector(selector, "e => getComputedStyle(e).color")
        return sum(float(n) for n in color.strip("rgba()").split(",")[:3])

    assert _brightness(".footer-brand") > _brightness(".footer-tagline")
    ctx.close()

"""JS behaviour of the static docs site, in a real browser.

Everything here is behaviour, not layout: a scroll handler, a stored
preference, a toggled attribute — none of it visible to a stylesheet diff or
a static HTML check. Runs against the same local static server as
tests/e2e/test_layout.py (see `docs_server_url` in tests/e2e/conftest.py), so
it needs no FastAPI app or review stack and runs in CI the same way that
file's docs checks do.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

pytestmark = pytest.mark.e2e


def _new_page(
    browser: Browser,
    base_url: str,
    *,
    width: int = 1280,
    height: int = 900,
    color_scheme: str | None = None,
    javascript_enabled: bool = True,
) -> tuple[BrowserContext, Page]:
    kwargs: dict[str, object] = {
        "viewport": {"width": width, "height": height},
        "base_url": base_url,
        "java_script_enabled": javascript_enabled,
    }
    if color_scheme is not None:
        kwargs["color_scheme"] = color_scheme
    ctx = browser.new_context(**kwargs)
    return ctx, ctx.new_page()


# ── Theme toggle ──────────────────────────────────────────────────────────


def test_theme_toggle_switches_data_theme(browser: Browser, docs_server_url: str) -> None:
    ctx, page = _new_page(browser, docs_server_url, color_scheme="light")
    page.goto("/docs.html")
    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert before == "light"
    page.click("#theme-toggle")
    after = page.evaluate("document.documentElement.getAttribute('data-theme')")
    ctx.close()
    assert after == "dark"


def test_theme_choice_persists_across_reload(browser: Browser, docs_server_url: str) -> None:
    ctx, page = _new_page(browser, docs_server_url, color_scheme="light")
    page.goto("/docs.html")
    page.click("#theme-toggle")
    assert page.evaluate("localStorage.getItem('ow-theme')") == "dark"
    page.reload()
    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    ctx.close()
    assert theme == "dark"


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_theme_follows_system_preference_when_nothing_stored(
    browser: Browser, docs_server_url: str, color_scheme: str
) -> None:
    ctx, page = _new_page(browser, docs_server_url, color_scheme=color_scheme)
    page.goto("/docs.html")
    assert page.evaluate("localStorage.getItem('ow-theme')") is None
    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    ctx.close()
    assert theme == color_scheme


# ── Mobile nav ────────────────────────────────────────────────────────────


def test_mobile_nav_toggle_opens_and_closes(browser: Browser, docs_server_url: str) -> None:
    ctx, page = _new_page(browser, docs_server_url, width=390)
    page.goto("/docs.html")
    toggle = page.locator(".nav-toggle")
    nav_links = page.locator("#nav-links")

    assert toggle.get_attribute("aria-expanded") == "false"
    assert not nav_links.is_visible()

    toggle.click()
    assert toggle.get_attribute("aria-expanded") == "true"
    assert nav_links.is_visible()

    toggle.click()
    assert toggle.get_attribute("aria-expanded") == "false"
    assert not nav_links.is_visible()
    ctx.close()


# ── Scroll-spy ────────────────────────────────────────────────────────────


def test_scroll_spy_marks_exactly_one_current_sidebar_link(
    browser: Browser, docs_server_url: str
) -> None:
    ctx, page = _new_page(browser, docs_server_url)
    page.goto("/docs.html")
    page.evaluate("document.getElementById('security').scrollIntoView()")
    page.wait_for_function(
        "document.querySelector('.sidebar-links a[aria-current=\"location\"]')"
        "?.getAttribute('href') === '#security'"
    )
    current = page.locator('.sidebar-links a[aria-current="location"]')
    count = current.count()
    ctx.close()
    assert count == 1


# ── No JavaScript ─────────────────────────────────────────────────────────


def test_docs_page_is_usable_with_javascript_disabled(
    browser: Browser, docs_server_url: str
) -> None:
    ctx, page = _new_page(browser, docs_server_url, javascript_enabled=False)
    page.goto("/docs.html")

    assert page.locator("#main-content").inner_text().strip() != ""

    sidebar_links = page.locator(".sidebar-links a")
    assert sidebar_links.count() > 0
    assert sidebar_links.first.is_visible()
    assert page.locator("#nav-links").is_visible()
    ctx.close()

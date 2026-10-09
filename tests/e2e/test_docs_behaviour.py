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
    page.goto("/en/docs/")
    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert before == "light"
    page.click("#theme-toggle")
    after = page.evaluate("document.documentElement.getAttribute('data-theme')")
    ctx.close()
    assert after == "dark"


def test_theme_choice_persists_across_reload(browser: Browser, docs_server_url: str) -> None:
    ctx, page = _new_page(browser, docs_server_url, color_scheme="light")
    page.goto("/en/docs/")
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
    page.goto("/en/docs/")
    assert page.evaluate("localStorage.getItem('ow-theme')") is None
    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    ctx.close()
    assert theme == color_scheme


# ── Mobile nav ────────────────────────────────────────────────────────────


def test_mobile_nav_toggle_opens_and_closes(browser: Browser, docs_server_url: str) -> None:
    ctx, page = _new_page(browser, docs_server_url, width=390)
    page.goto("/en/docs/")
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


@pytest.mark.parametrize("url", ["/en/changelog/"])
@pytest.mark.parametrize("below_nav", [0, 60, 200])
def test_scroll_spy_marks_the_section_whose_heading_tops_the_view(
    browser: Browser, docs_server_url: str, url: str, below_nav: int
) -> None:
    """A section's heading just under the sticky nav is the one being read, not the tail of
    the previous section above it (Chrome check: "Container Images" lit over "Installation")."""
    ctx, page = _new_page(browser, docs_server_url, width=1920, height=1080)
    page.goto(url)
    target = page.evaluate("[...document.querySelectorAll('.docs-section[id]')][3].id")
    page.evaluate(
        """([id, gap]) => { const nav = document.querySelector('.site-nav').offsetHeight;
             const top = document.getElementById(id).getBoundingClientRect().top + scrollY;
             window.scrollTo({top: top - nav - gap, behavior: 'instant'}); }""",
        [target, below_nav],
    )
    page.wait_for_timeout(100)
    active = page.evaluate("document.querySelector('.sidebar-links a.active')?.hash")
    ctx.close()
    assert active == f"#{target}", (url, below_nav, active)


# ── No JavaScript ─────────────────────────────────────────────────────────


def test_docs_page_is_usable_with_javascript_disabled(
    browser: Browser, docs_server_url: str
) -> None:
    ctx, page = _new_page(browser, docs_server_url, javascript_enabled=False)
    page.goto("/en/docs/ldap/")

    assert page.locator("#main-content").inner_text().strip() != ""

    sidebar_links = page.locator(".sidebar-links a")
    assert sidebar_links.count() > 0
    assert sidebar_links.first.is_visible()
    assert page.locator("#nav-links").is_visible()
    ctx.close()


@pytest.mark.parametrize(
    ("old", "lands"),
    [
        ("/en/docs/#helm", "/en/docs/kubernetes/"),
        ("/en/docs/#own-account", "/en/docs/admin/#own-account"),
        ("/docs.html#onion-address", "/en/docs/onion/"),
        ("/docs.html#first-run", "/en/docs/install/#first-run"),
    ],
)
def test_a_one_pager_anchor_lands_on_its_page(
    browser: Browser, docs_server_url: str, old: str, lands: str
) -> None:
    ctx, page = _new_page(browser, docs_server_url)
    page.goto(old)
    page.wait_for_url(f"**{lands}")
    ctx.close()


# ── Docs sidebar ──────────────────────────────────────────────────────────


def test_a_docs_page_marks_itself_in_an_open_sidebar_group(
    browser: Browser, docs_server_url: str
) -> None:
    ctx, page = _new_page(browser, docs_server_url, width=1920, height=1080)
    page.goto("/en/docs/ldap/")
    current = page.locator('.sidebar-links a[aria-current="page"]')
    assert current.count() == 1 and current.get_attribute("href") == "/en/docs/ldap/"
    assert current.is_visible()
    ctx.close()


def test_the_docs_menu_starts_closed_on_a_phone(browser: Browser, docs_server_url: str) -> None:
    ctx, page = _new_page(browser, docs_server_url, width=390, height=844)
    page.goto("/en/docs/ldap/")
    menu = page.locator(".docs-menu")
    assert menu.get_attribute("open") is None
    # the article starts on the first screen, not under 30 links
    top = page.evaluate("document.querySelector('.docs-article h1').getBoundingClientRect().top")
    assert top < 844, top
    page.locator(".docs-menu > summary").click()
    assert menu.get_attribute("open") is not None
    ctx.close()


def test_a_phone_turned_to_landscape_gets_the_menu_back(
    browser: Browser, docs_server_url: str
) -> None:
    """Above 768 px the menu's summary is hidden: a menu left closed would leave no toggle."""
    ctx, page = _new_page(browser, docs_server_url, width=390, height=844)
    page.goto("/en/docs/ldap/")
    menu = page.locator(".docs-menu")
    assert menu.get_attribute("open") is None
    page.set_viewport_size({"width": 1024, "height": 768})
    page.wait_for_function("document.querySelector('.docs-menu').open")
    assert not page.locator(".docs-menu > summary").is_visible()
    assert page.locator('.sidebar-links a[aria-current="page"]').is_visible()
    ctx.close()


_SCROLL_BOXES = """[...document.querySelectorAll('.table-scroll, pre')].map(b =>
  [b.scrollWidth > b.clientWidth, b.tabIndex,
   b.getAttribute('role'), b.getAttribute('aria-label')])"""


def _assert_only_overflowing_boxes_are_named_tab_stops(
    boxes: list[list[object]], *, some_fit: bool = True
) -> None:
    wide = [b for b in boxes if b[0]]
    fits = [b for b in boxes if not b[0]]
    assert wide and (fits or not some_fit), boxes
    assert all(b[1] == 0 and b[2] == "region" and b[3] for b in wide), wide
    assert all(b[1] == -1 and b[2] is None and b[3] is None for b in fits), fits


@pytest.mark.parametrize("width", [1920, 390])
def test_a_box_that_scrolls_sideways_is_a_named_tab_stop(
    browser: Browser, docs_server_url: str, width: int
) -> None:
    """In the 1200 px frame a wide table or code line scrolls in its own box; a keyboard user
    must be able to focus it to scroll it, and a region needs a name (axe
    scrollable-region-focusable). A box that fits is no tab stop. The install page's long
    commands are wider than the column; its tables fit (the desktop table guard)."""
    ctx, page = _new_page(browser, docs_server_url, width=width)
    page.goto("/en/docs/install/")
    page.evaluate("document.fonts.ready")
    boxes = page.evaluate(_SCROLL_BOXES)
    ctx.close()
    # On a phone no box has to fit.
    _assert_only_overflowing_boxes_are_named_tab_stops(boxes, some_fit=width > 390)


def test_a_box_that_stops_scrolling_after_a_resize_is_no_tab_stop(
    browser: Browser, docs_server_url: str
) -> None:
    ctx, page = _new_page(browser, docs_server_url, width=390, height=844)
    page.goto("/en/docs/install/")
    page.evaluate("document.fonts.ready")
    narrow = sum(1 for b in page.evaluate(_SCROLL_BOXES) if b[1] == 0)
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_function(
        f"[...document.querySelectorAll('.table-scroll, pre')].filter(b => b.tabIndex === 0)"
        f".length < {narrow}"
    )
    boxes = page.evaluate(_SCROLL_BOXES)
    ctx.close()
    _assert_only_overflowing_boxes_are_named_tab_stops(boxes)


def test_the_docs_menu_is_open_without_javascript(browser: Browser, docs_server_url: str) -> None:
    ctx, page = _new_page(browser, docs_server_url, width=390, javascript_enabled=False)
    page.goto("/en/docs/ldap/")
    assert page.locator(".docs-menu").get_attribute("open") is not None
    ctx.close()


_SETTLED = """() => new Promise(done => {
  let y = scrollY, still = 0;
  const tick = setInterval(() => {
    if (scrollY !== y) { y = scrollY; still = 0; }
    else if (++still > 5) { clearInterval(tick); done(true); }
  }, 100);
})"""


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize(
    "url",
    [
        "/en/docs/onion/#main-content",
        "/en/docs/install/#first-run",
        "/en/docs/admin/#own-account",
        "/en/#how-it-works",
        "/en/changelog/#v2-0-0",
        "/en/blog/whats-new-in-2-0/#main-content",
    ],
)
def test_a_deep_link_target_is_not_under_the_sticky_nav(
    browser: Browser, docs_server_url: str, url: str, width: int
) -> None:
    """The nav is sticky; without scroll-padding a #target lands behind it, and an
    image whose width/height lie shifts the target when it loads (the one-pager's #demo-mode)."""
    ctx, page = _new_page(browser, docs_server_url, width=width)
    page.goto(url)
    page.wait_for_load_state("networkidle")
    page.wait_for_function(_SETTLED)
    target_top, nav_bottom = page.evaluate(
        """() => [document.getElementById(location.hash.slice(1)).getBoundingClientRect().top,
                  document.querySelector('.site-nav').getBoundingClientRect().bottom]"""
    )
    assert target_top >= nav_bottom, (url, width, target_top, nav_bottom)
    ctx.close()

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

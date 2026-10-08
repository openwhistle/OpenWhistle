"""Docs search: Pagefind's own pagefind.js under our small UI (spec: `/`, <dialog>, highlight).

The term reaches a result in the fragment (#highlight=), not in ?highlight=: the privacy
policy says search terms are not transmitted, and a query string is sent with the request.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e.conftest import run_axe

pytestmark = pytest.mark.e2e

TERM = "hs_ed25519_secret_key"


def _search(page: Page, term: str = TERM) -> None:
    page.goto("/en/docs/")
    page.keyboard.press("/")
    page.locator("#docs-search-input").fill(term)
    page.locator(".docs-search-results a").first.wait_for()


def test_slash_opens_search_and_a_result_highlights_the_term(
    browser: Browser, docs_server_url: str
) -> None:
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    page.goto("/en/docs/")
    page.keyboard.press("/")
    dialog = page.locator("#docs-search")
    assert dialog.evaluate("d => d.open")
    page.locator("#docs-search-input").fill(TERM)
    first = page.locator(".docs-search-results a").first
    first.wait_for()
    assert first.get_attribute("href").startswith("/en/docs/onion/#highlight=")
    first.click()
    page.wait_for_url(f"**/en/docs/onion/#highlight={TERM}")
    mark = page.locator("mark.pagefind-highlight").first
    mark.wait_for()
    assert mark.text_content() == TERM
    assert mark.is_visible() and mark.evaluate("m => m.getBoundingClientRect().top > 0")
    ctx.close()


def test_the_term_never_leaves_the_browser(browser: Browser, docs_server_url: str) -> None:
    """Search, then open a result: every request goes to this site and none carries the term."""
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    seen: list[str] = []
    page.on("request", lambda r: seen.append(f"{r.url} {r.headers}"))
    _search(page)
    page.locator(".docs-search-results a").first.click()
    page.locator("mark.pagefind-highlight").first.wait_for()
    ctx.close()
    host = urlsplit(docs_server_url).netloc
    assert any("/pagefind/" in s for s in seen), seen  # the index was loaded
    assert all(urlsplit(s.split()[0]).netloc == host for s in seen), seen
    assert not [s for s in seen if TERM in s], seen


def test_slash_inside_a_field_types_a_slash(browser: Browser, docs_server_url: str) -> None:
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    page.goto("/en/docs/")
    page.keyboard.press("/")
    page.locator("#docs-search-input").type("a/b")
    assert page.locator("#docs-search-input").input_value() == "a/b"
    ctx.close()


def test_escape_closes_and_focus_returns_to_the_button(
    browser: Browser, docs_server_url: str
) -> None:
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    page.goto("/en/docs/")
    page.keyboard.press("/")
    page.keyboard.press("Escape")
    assert not page.locator("#docs-search").evaluate("d => d.open")
    assert page.evaluate("document.activeElement.hasAttribute('data-search-open')")
    ctx.close()


def test_an_excerpt_carries_no_markup_but_the_marks(browser: Browser, docs_server_url: str) -> None:
    """search.js sets the excerpt as HTML: Pagefind must have escaped the page's own text.
    `<username>` stands in the docs as text; it must come back as text, not as an element."""
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    _search(page, "username")
    tags, text = page.evaluate(
        """() => { const ps = [...document.querySelectorAll('.docs-search-results p')];
                   return [ps.flatMap(p => [...p.querySelectorAll('*')].map(e => e.tagName)),
                           ps.map(p => p.textContent).join(' ')]; }"""
    )
    ctx.close()
    assert "<username>" in text and set(tags) == {"MARK"}, (tags, text)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_open_search_passes_axe(
    browser: Browser, docs_server_url: str, axe_source: str, theme: str
) -> None:
    ctx = browser.new_context(base_url=docs_server_url, reduced_motion="reduce")
    ctx.add_init_script(f"localStorage.setItem('ow-theme','{theme}')")
    page = ctx.new_page()
    _search(page, "onion")
    violations = run_axe(page, axe_source)
    ctx.close()
    assert not violations, [(v["id"], [n["target"] for n in v["nodes"]]) for v in violations]


def test_on_a_phone_the_search_fills_the_screen(browser: Browser, docs_server_url: str) -> None:
    ctx = browser.new_context(base_url=docs_server_url, viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    _search(page)
    box = page.locator("#docs-search").bounding_box()
    wider = page.evaluate("document.documentElement.scrollWidth > innerWidth")
    ctx.close()
    assert box and box["x"] == 0 and box["width"] == 390, box
    assert not wider


def test_without_javascript_there_is_no_dead_search_button(
    browser: Browser, docs_server_url: str
) -> None:
    ctx = browser.new_context(base_url=docs_server_url, java_script_enabled=False)
    page = ctx.new_page()
    page.goto("/en/docs/")
    assert not page.locator("[data-search-open]").is_visible()
    ctx.close()

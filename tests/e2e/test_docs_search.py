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
    # Reduced motion: the scroll to the mark is instant, not mid-animation when measured.
    ctx = browser.new_context(base_url=docs_server_url, reduced_motion="reduce")
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
    # The first match lies below the fold; search.js scrolls it into the window.
    below_fold, top, bottom, height = mark.evaluate(
        """m => { const r = m.getBoundingClientRect();
                  return [r.top + scrollY > innerHeight, r.top, r.bottom, innerHeight]; }"""
    )
    ctx.close()
    assert below_fold and 0 <= top and bottom <= height, (top, bottom, height)


def test_the_term_never_leaves_the_browser(browser: Browser, docs_server_url: str) -> None:
    """Search, then open a result: every request goes to this site and none carries the term."""
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    seen: list[str] = []
    page.on("request", lambda r: seen.append(f"{r.url} {r.headers} {r.post_data}"))
    _search(page)
    page.locator(".docs-search-results a").first.click()
    page.locator("mark.pagefind-highlight").first.wait_for()
    ctx.close()
    host = urlsplit(docs_server_url).netloc
    # The search ran on the index here: without these requests the test proves nothing.
    assert any(f"/pagefind/{d}/" in s for s in seen for d in ("index", "fragment")), seen
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


def test_closing_restores_focus_without_scrolling_the_page(
    browser: Browser, docs_server_url: str
) -> None:
    """On a phone the search button sits at the top of the page: focusing it on close
    would jump a reader who pressed `/` mid-page back to the top."""
    ctx = browser.new_context(
        base_url=docs_server_url, viewport={"width": 390, "height": 844}, reduced_motion="reduce"
    )
    page = ctx.new_page()
    page.goto("/en/docs/onion/")
    page.evaluate("window.scrollTo({top: 1500, behavior: 'instant'})")
    before = page.evaluate("scrollY")
    page.keyboard.press("/")
    page.keyboard.press("Escape")
    # The close event runs a task later: wait until it has put the focus somewhere.
    page.wait_for_function("document.activeElement.hasAttribute('data-search-open')")
    after = page.evaluate("scrollY")
    ctx.close()
    assert before > 0 and after == before, (before, after)


def test_a_result_count_names_the_listed_part(browser: Browser, docs_server_url: str) -> None:
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    _search(page, "the")
    listed = page.locator(".docs-search-results li").count()
    status = page.locator(".docs-search-status").text_content()
    ctx.close()
    assert listed == 8 and status and status.startswith("8 of "), (listed, status)


def test_search_says_so_when_pagefind_does_not_load(browser: Browser, docs_server_url: str) -> None:
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    page.route("**/pagefind/pagefind.js", lambda route: route.abort())
    page.goto("/en/docs/")
    page.keyboard.press("/")
    page.locator("#docs-search-input").fill("onion")
    status = page.locator(".docs-search-status")
    status.filter(has_text="unavailable").wait_for()
    ctx.close()


def test_a_broken_highlight_fragment_is_ignored(browser: Browser, docs_server_url: str) -> None:
    """A malformed or empty #highlight= marks nothing, throws nothing, loads nothing."""
    ctx = browser.new_context(base_url=docs_server_url)
    page = ctx.new_page()
    errors: list[str] = []
    loaded: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: loaded.append(r.url))
    for fragment in ("%E0", "%20"):
        page.goto("about:blank")  # else the second goto only changes the fragment, no reload
        page.goto(f"/en/docs/onion/#highlight={fragment}")
        page.wait_for_load_state("networkidle")
    marks = page.locator("mark").count()
    ctx.close()
    highlight = [u for u in loaded if "pagefind-highlight" in u]
    assert not errors and marks == 0 and not highlight, (errors, marks, highlight)


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

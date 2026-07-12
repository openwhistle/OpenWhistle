"""End-to-end verification that the strict CSP does not break any page.

A real browser is the only place inline-handler / inline-style / missing-nonce
violations actually surface: the browser refuses the offending construct and
emits a console error (and, for scripts, a pageerror) at load time. These tests
load every significant page — and drive a couple of interactions — asserting
that the console carries no Content-Security-Policy violation.

Runs in the Playwright E2E CI job against the demo stack.
"""

from __future__ import annotations

from playwright.sync_api import Page

_CSP_MARKERS = ("Content Security Policy", "Refused to", "violates the following")


def _collect_violations(page: Page) -> list[str]:
    hits: list[str] = []

    def on_console(msg) -> None:  # type: ignore[no-untyped-def]
        if msg.type == "error" and any(m in msg.text for m in _CSP_MARKERS):
            hits.append(msg.text)

    def on_pageerror(err) -> None:  # type: ignore[no-untyped-def]
        text = str(err)
        if any(m in text for m in _CSP_MARKERS):
            hits.append(text)

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    return hits


def _assert_clean(page: Page, url: str) -> None:
    hits = _collect_violations(page)
    page.goto(url)
    page.wait_for_load_state("networkidle")
    assert not hits, f"CSP violations on {url}:\n" + "\n".join(hits)


def test_csp_public_pages(page: Page, base_url: str) -> None:
    for path in ("/", "/submit", "/status", "/admin/login"):
        _assert_clean(page, f"{base_url}{path}")


def test_csp_theme_toggle_still_works(page: Page, base_url: str) -> None:
    """The theme toggle used to be an inline onclick — verify the rewired
    listener fires under CSP and no violation is logged."""
    hits = _collect_violations(page)
    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")
    before = page.get_attribute("html", "data-theme")
    page.click("#theme-toggle")
    after = page.get_attribute("html", "data-theme")
    assert before != after, "theme toggle did not change the theme (handler blocked?)"
    assert not hits, "CSP violations while toggling theme:\n" + "\n".join(hits)


def test_csp_admin_pages(admin_page: Page, base_url: str) -> None:
    for path in (
        "/admin/dashboard",
        "/admin/stats",
        "/admin/users",
        "/admin/categories",
        "/admin/locations",
        "/admin/audit-log",
    ):
        _assert_clean(admin_page, f"{base_url}{path}")


def test_csp_admin_report_detail(admin_page: Page, base_url: str) -> None:
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    link = admin_page.query_selector("a[href*='/admin/reports/']")
    if not link:
        return  # no reports seeded — nothing to check
    href = link.get_attribute("href")
    assert href
    _assert_clean(admin_page, f"{base_url}{href}")


def test_csp_submit_wizard_navigation(page: Page, base_url: str) -> None:
    """The submit wizard used inline onclick/onchange for step navigation;
    verify advancing a step raises no CSP violation."""
    hits = _collect_violations(page)
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    # Advancing the first step exercises the rewired navigation handlers.
    nxt = page.query_selector("button[type='submit'], .btn-primary")
    if nxt:
        nxt.click()
        page.wait_for_load_state("networkidle")
    assert not hits, "CSP violations in submit wizard:\n" + "\n".join(hits)

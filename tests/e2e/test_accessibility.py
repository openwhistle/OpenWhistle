"""Accessibility tests using axe-core injection.

axe-core is downloaded once per session via the axe_source fixture in conftest.py.
If network is unavailable, tests are skipped gracefully.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_USERNAME,
    DEMO_CASE_IN_REVIEW,
    run_axe,
)

pytestmark = pytest.mark.e2e


def _check_axe(page: Page, axe_source: str, context: str) -> None:
    """Run axe and assert no critical/serious violations."""
    if not axe_source:
        pytest.skip("axe-core unavailable — network required")
    violations = run_axe(page, axe_source)
    assert violations == [], (
        f"Accessibility violations on {context}:\n"
        + "\n".join(
            f"  [{v.get('impact', 'unknown')}] {v.get('id', '')}: {v.get('description', '')}"
            for v in violations
        )
    )


def test_axe_submit_page_step1(page: Page, base_url: str, axe_source: str) -> None:
    """No critical/serious axe violations on /submit (step 1)."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    _check_axe(page, axe_source, "/submit")


def test_axe_status_page(page: Page, base_url: str, axe_source: str) -> None:
    """No critical/serious axe violations on /status."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    _check_axe(page, axe_source, "/status")


def test_axe_admin_login(page: Page, base_url: str, axe_source: str) -> None:
    """No critical/serious axe violations on /admin/login."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    _check_axe(page, axe_source, "/admin/login")


def test_axe_admin_mfa(page: Page, base_url: str, axe_source: str) -> None:
    """Get to MFA page and check accessibility."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', DEMO_ADMIN_USERNAME)
    page.fill('input[name="password"]', DEMO_ADMIN_PASSWORD)
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/login/mfa**")
    page.wait_for_load_state("networkidle")
    _check_axe(page, axe_source, "/admin/login/mfa")


def test_axe_admin_dashboard(admin_page: Page, base_url: str, axe_source: str) -> None:
    """No critical/serious axe violations on /admin/dashboard."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    _check_axe(admin_page, axe_source, "/admin/dashboard")


def test_axe_admin_report_detail(admin_page: Page, base_url: str, axe_source: str) -> None:
    """No critical/serious axe violations on a report detail page."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    first_report = admin_page.locator("table tbody tr td a.btn").first
    if first_report.count() == 0:
        pytest.skip("No report links found on dashboard")
    first_report.click()
    admin_page.wait_for_load_state("networkidle")
    _check_axe(admin_page, axe_source, "/admin/reports/<id>")


def test_axe_status_with_report(page: Page, base_url: str, axe_source: str) -> None:
    """No critical/serious axe violations on status page after loading a real report."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="case_number"]', DEMO_CASE_IN_REVIEW["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_IN_REVIEW["pin"])
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    _check_axe(page, axe_source, "/status (with report)")


def test_axe_submit_german(page: Page, base_url: str, axe_source: str) -> None:
    """No critical/serious axe violations on /submit in German."""
    page.goto(f"{base_url}/submit?lang=de")
    page.wait_for_load_state("networkidle")
    _check_axe(page, axe_source, "/submit (de)")


def test_skip_link_present(page: Page, base_url: str) -> None:
    """Skip-to-content link must be in the DOM on all major pages."""
    for path in ["/submit", "/status", "/admin/login"]:
        page.goto(f"{base_url}{path}")
        page.wait_for_load_state("networkidle")
        skip = page.locator(".skip-link, a[href='#main'], a[href*='skip'], a[href='#main-content']")
        assert skip.count() >= 1, f"No skip link found on {path}"


def test_keyboard_tab_order_submit(page: Page, base_url: str) -> None:
    """Tab through the submit form — first focusable element should be reachable."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    page.keyboard.press("Tab")
    focused_tag: str = page.evaluate("document.activeElement.tagName")
    assert focused_tag in ("A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"), (
        f"First tab focus landed on unexpected element: {focused_tag}"
    )


def test_keyboard_tab_order_status(page: Page, base_url: str) -> None:
    """Tab through the status form — focusable elements are reachable."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    page.keyboard.press("Tab")
    focused_tag: str = page.evaluate("document.activeElement.tagName")
    assert focused_tag in ("A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"), (
        f"First tab focus on /status landed on unexpected element: {focused_tag}"
    )


def test_form_labels_on_login(page: Page, base_url: str) -> None:
    """All form inputs on the login page have associated labels."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    # Each named input should have a corresponding label
    inputs = page.locator('input[name="username"], input[name="password"]').all()
    assert len(inputs) >= 2, "Expected at least username and password inputs on login page"
    for inp in inputs:
        inp_id = inp.get_attribute("id")
        if inp_id:
            label = page.locator(f'label[for="{inp_id}"]')
            assert label.count() > 0, (
                f"Input #{inp_id} has no associated <label for='...'>"
            )

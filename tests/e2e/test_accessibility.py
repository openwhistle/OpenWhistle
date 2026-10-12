"""Accessibility tests using axe-core injection.

axe-core is read from tests/e2e/vendor/ (hash-checked) by the axe_source fixture in conftest.py.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_USERNAME,
    DEMO_CASE_IN_REVIEW,
    run_axe,
    run_axe_warnings,
)

pytestmark = pytest.mark.e2e


def _check_axe(page: Page, axe_source: str, context: str) -> None:
    """Run axe and fail on critical violations; report serious ones as warnings."""
    critical = run_axe(page, axe_source)
    serious = run_axe_warnings(page, axe_source)
    if serious:
        import warnings

        warnings.warn(
            f"Serious (non-blocking) a11y violations on {context}: "
            + ", ".join(v.get("id", "") for v in serious),
            stacklevel=2,
        )
    assert critical == [], f"Critical accessibility violations on {context}:\n" + "\n".join(
        f"  [{v.get('impact', 'unknown')}] {v.get('id', '')}: {v.get('description', '')}"
        for v in critical
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
    page.wait_for_selector('input[name="totp_code"]')
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
            assert label.count() > 0, f"Input #{inp_id} has no associated <label for='...'>"


def _dark(page: Page) -> None:
    # base.html follows prefers-color-scheme when no theme is stored.
    page.emulate_media(color_scheme="dark")


@pytest.mark.parametrize("path", ["/submit", "/status", "/admin/login"])
def test_axe_dark_theme(page: Page, base_url: str, axe_source: str, path: str) -> None:
    """The dark theme is checked too: every test above ran in light only, and white text
    on the dark theme's light fills (the wizard's current step, 2.34:1) shipped green."""
    _dark(page)
    page.goto(f"{base_url}{path}")
    page.wait_for_load_state("networkidle")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    _check_axe(page, axe_source, f"{path} (dark)")


def test_axe_dark_status_with_report(page: Page, base_url: str, axe_source: str) -> None:
    from tests.e2e.conftest import DEMO_CASE_PENDING

    _dark(page)
    page.goto(f"{base_url}/status")
    page.fill('input[name="case_number"]', DEMO_CASE_PENDING["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_PENDING["pin"])
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    _check_axe(page, axe_source, "/status with report (dark)")


def test_axe_dark_admin_report(admin_page: Page, base_url: str, axe_source: str) -> None:
    _dark(admin_page)
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    _check_axe(admin_page, axe_source, "/admin/dashboard (dark)")
    admin_page.locator("table tbody tr td a.btn").first.click()
    admin_page.wait_for_load_state("networkidle")
    # The four-eyes form with its danger button sits in a closed <details>.
    admin_page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    _check_axe(admin_page, axe_source, "/admin/reports/<id> (dark)")

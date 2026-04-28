"""E2E tests for session expiry and invalid session handling."""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_expired_session_redirects_to_login(admin_page: Page, base_url: str) -> None:
    """After clearing the session, protected admin routes are no longer accessible."""
    # admin_session is HttpOnly — cannot be corrupted via document.cookie.
    # Clear all cookies instead to properly simulate session expiry.
    admin_page.context.clear_cookies()
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    final_url = admin_page.url
    body = admin_page.content()
    # App may redirect to /admin/login OR return a 401 JSON/error response
    assert (
        "/admin/login" in final_url
        or "/login" in final_url
        or "Unauthorized" in body
        or "401" in body
    ), f"Expected login redirect or 401 after session clear, but got: {final_url}"


def test_no_session_redirects_to_login(page: Page, base_url: str) -> None:
    """A fresh browser with no session cookie is not admitted to /admin/dashboard."""
    page.context.clear_cookies()
    page.goto(f"{base_url}/admin/dashboard")
    page.wait_for_load_state("networkidle")
    final_url = page.url
    body = page.content()
    assert (
        "/admin/login" in final_url
        or "/login" in final_url
        or "Unauthorized" in body
        or "401" in body
    ), f"Expected redirect to login or 401 for unauthenticated request, but got: {final_url}"


def test_expired_session_cannot_access_protected_routes(admin_page: Page, base_url: str) -> None:
    """After clearing the session, all protected admin routes are inaccessible."""
    admin_page.context.clear_cookies()
    protected_routes = [
        "/admin/categories",
        "/admin/users",
        "/admin/audit-log",
        "/admin/stats",
    ]
    for route in protected_routes:
        admin_page.goto(f"{base_url}{route}")
        admin_page.wait_for_load_state("networkidle")
        final_url = admin_page.url
        body = admin_page.content()
        assert (
            "/admin/login" in final_url
            or "/login" in final_url
            or "Unauthorized" in body
            or "401" in body
        ), f"Route {route} accessible after session clear. Final URL: {final_url}"


def test_whistleblower_session_handles_invalid_token(page: Page, base_url: str) -> None:
    """The status page handles an invalid session token gracefully (shows form, not 500)."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    # Corrupt the session_token hidden field via JS
    page.evaluate(
        "var el = document.querySelector('input[name=\"session_token\"]'); "
        "if (el) el.value = 'invalid-session-token-xyz';"
    )
    # Submit with invalid credentials
    case_input = page.locator('input[name="case_number"]')
    pin_input = page.locator('input[name="pin"]')
    if case_input.count() > 0 and pin_input.count() > 0:
        page.fill('input[name="case_number"]', "OW-FAKE-99999")
        page.fill('input[name="pin"]', "wrong-pin")
        page.click("button.btn-primary")
        page.wait_for_load_state("networkidle")
        # Should show error or form, not 500
        assert page.url != f"{base_url}/500"
        body = page.content()
        assert "500" not in page.title()
        assert "Internal Server Error" not in body

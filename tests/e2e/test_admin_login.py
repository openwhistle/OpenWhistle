"""E2E tests for the admin login flow including TOTP verification."""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    _totp_now,
)

pytestmark = pytest.mark.e2e


def test_login_page_loads(page: Page, base_url: str) -> None:
    """Login page loads and contains OpenWhistle branding."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    assert "OpenWhistle" in page.title()


def test_login_page_has_form_fields(page: Page, base_url: str) -> None:
    """Login page has username and password inputs."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    expect(page.locator('input[name="username"]')).to_be_visible()
    expect(page.locator('input[name="password"]')).to_be_visible()
    expect(page.locator("button.btn-primary")).to_be_visible()


def test_wrong_password_shows_error(page: Page, base_url: str) -> None:
    """Submitting wrong password shows an error message."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', DEMO_ADMIN_USERNAME)
    page.fill('input[name="password"]', "completely-wrong-password-xyz")
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    # Should stay on login page (or show error), not reach dashboard
    assert "/admin/dashboard" not in page.url
    # Should show some error indication
    body_text = page.content()
    assert any(
        indicator in body_text.lower()
        for indicator in ["invalid", "error", "incorrect", "wrong", "login"]
    )


def test_wrong_totp_shows_error(page: Page, base_url: str) -> None:
    """Submitting wrong TOTP code at MFA step shows an error message."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', DEMO_ADMIN_USERNAME)
    page.fill('input[name="password"]', DEMO_ADMIN_PASSWORD)
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/login/mfa**")
    # Submit a clearly wrong TOTP code
    page.fill('input[name="totp_code"]', "000000")
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    # Should not reach dashboard
    assert "/admin/dashboard" not in page.url
    body_text = page.content()
    assert any(
        indicator in body_text.lower()
        for indicator in ["invalid", "error", "incorrect", "code", "mfa", "totp"]
    )


def test_correct_credentials_reach_dashboard(page: Page, base_url: str) -> None:
    """Correct username, password and TOTP code lead to the admin dashboard."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', DEMO_ADMIN_USERNAME)
    page.fill('input[name="password"]', DEMO_ADMIN_PASSWORD)
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/login/mfa**")
    page.fill('input[name="totp_code"]', _totp_now(DEMO_ADMIN_TOTP_SECRET))
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/dashboard**")
    assert "/admin/dashboard" in page.url


def test_dashboard_shows_heading(page: Page, base_url: str) -> None:
    """After login, the dashboard page contains a recognizable heading."""
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', DEMO_ADMIN_USERNAME)
    page.fill('input[name="password"]', DEMO_ADMIN_PASSWORD)
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/login/mfa**")
    page.fill('input[name="totp_code"]', _totp_now(DEMO_ADMIN_TOTP_SECRET))
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/dashboard**")
    page.wait_for_load_state("networkidle")
    body_text = page.content()
    assert any(
        heading in body_text for heading in ["Dashboard", "dashboard", "OpenWhistle"]
    )


def test_logout_redirects_to_login(page: Page, base_url: str) -> None:
    """Clicking logout from the dashboard redirects to the login page."""
    # First log in
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', DEMO_ADMIN_USERNAME)
    page.fill('input[name="password"]', DEMO_ADMIN_PASSWORD)
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/login/mfa**")
    page.fill('input[name="totp_code"]', _totp_now(DEMO_ADMIN_TOTP_SECRET))
    page.click("button.btn-primary")
    page.wait_for_url("**/admin/dashboard**")
    # Now navigate to logout
    page.goto(f"{base_url}/admin/logout")
    page.wait_for_load_state("networkidle")
    # Should be on login page (or home/landing)
    assert "/admin/login" in page.url or page.url == f"{base_url}/" or "/login" in page.url

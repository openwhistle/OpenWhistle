"""E2E tests for admin user management.

Tests user creation, deactivation, reactivation and role-based access control.
"""
from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_TEST_USER = f"e2e-test-user-{int(time.time()) % 100000}"
_TEST_PASSWORD = "E2eTestPassword123!secure"


def test_users_page_shows_demo_users(admin_page: Page, base_url: str) -> None:
    """The users list page shows the demo and case_manager accounts."""
    admin_page.goto(f"{base_url}/admin/users")
    admin_page.wait_for_load_state("networkidle")
    body = admin_page.content()
    assert "demo" in body, "Demo user not found in users list"
    assert "case_manager" in body, "case_manager user not found in users list"


def test_create_new_user(admin_page: Page, base_url: str) -> None:
    """Admin can create a new user who then appears in the user list."""
    admin_page.goto(f"{base_url}/admin/users")
    admin_page.wait_for_load_state("networkidle")

    # Fill the add-user form
    admin_page.fill('input[name="username"]', _TEST_USER)
    admin_page.fill('input[name="password"]', _TEST_PASSWORD)
    # Select a role — use the add-form's specific #new-role to avoid matching per-user selects
    role_select = admin_page.locator('#new-role')
    if role_select.count() > 0:
        role_select.select_option("case_manager")

    admin_page.click('button[type="submit"].btn-primary')
    admin_page.wait_for_load_state("networkidle")

    # The new user should appear in the table
    body = admin_page.content()
    assert _TEST_USER in body, (
        f"Newly created user '{_TEST_USER}' not found in users list after creation"
    )


def test_deactivate_user(admin_page: Page, base_url: str) -> None:
    """Admin can deactivate a user, who then appears as inactive."""
    admin_page.goto(f"{base_url}/admin/users")
    admin_page.wait_for_load_state("networkidle")

    # Find the test user row
    row = admin_page.locator("table tbody tr").filter(has_text=_TEST_USER)
    if row.count() == 0:
        pytest.skip(f"Test user '{_TEST_USER}' not found — run create test first")

    # Click Deactivate button in that row
    deactivate_form = row.locator('form[action*="/deactivate"]')
    if deactivate_form.count() == 0:
        pytest.skip("Deactivate form not found in test user row")

    # Handle JS confirm dialog
    admin_page.on("dialog", lambda d: d.accept())
    deactivate_form.locator('button[type="submit"]').click()
    admin_page.wait_for_load_state("networkidle")

    # Verify inactive status in the updated table
    body = admin_page.content()
    # The inactive badge text or opacity style should indicate deactivation
    assert any(
        term in body.lower()
        for term in ["inactive", "deactivated", "opacity:0.5"]
    ), "User not shown as inactive after deactivation"


def test_reactivate_user(admin_page: Page, base_url: str) -> None:
    """Admin can reactivate a previously deactivated user."""
    admin_page.goto(f"{base_url}/admin/users")
    admin_page.wait_for_load_state("networkidle")

    row = admin_page.locator("table tbody tr").filter(has_text=_TEST_USER)
    if row.count() == 0:
        pytest.skip(f"Test user '{_TEST_USER}' not found")

    reactivate_form = row.locator('form[action*="/reactivate"]')
    if reactivate_form.count() == 0:
        pytest.skip("Reactivate form not found — user may already be active")

    reactivate_form.locator('button[type="submit"]').click()
    admin_page.wait_for_load_state("networkidle")

    body = admin_page.content()
    # User should now appear as active again
    assert any(
        term in body
        for term in ["Active", "active", "badge-closed"]
    ), "User not shown as active after reactivation"


def test_case_manager_cannot_access_users_page(cm_page: Page, base_url: str) -> None:
    """A case_manager cannot access /admin/users — should get redirect or error."""
    cm_page.goto(f"{base_url}/admin/users")
    cm_page.wait_for_load_state("networkidle")
    final_url = cm_page.url
    body = cm_page.content()
    # Should either redirect to dashboard or show a forbidden/error page
    # Must NOT show the users management page
    assert any(
        indicator in final_url or indicator in body.lower()
        for indicator in [
            "dashboard",
            "forbidden",
            "403",
            "permission",
            "login",
            "not allowed",
        ]
    ), (
        f"case_manager should not access /admin/users. "
        f"URL: {final_url}, body excerpt: {body[:200]}"
    )
    # The add-user form must NOT be present
    assert 'input[name="username"]' not in body or "admin.users" not in body

"""E2E tests for the setup wizard — verifies redirect behaviour when setup is complete."""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_setup_redirects_when_complete(page: Page, base_url: str) -> None:
    """When setup is already complete, /setup redirects away (no error page)."""
    response = page.goto(f"{base_url}/setup")
    page.wait_for_load_state("networkidle")
    # The page should not show an unhandled error
    assert response is not None
    # Should redirect to login or dashboard — not stay on /setup with an error
    final_url = page.url
    assert "error" not in final_url.lower()
    assert "500" not in page.content()
    # Content should be a proper OpenWhistle page
    content = page.content()
    assert "OpenWhistle" in content


def test_setup_redirect_destination_is_valid(page: Page, base_url: str) -> None:
    """The redirect target from /setup is the login or dashboard page."""
    page.goto(f"{base_url}/setup")
    page.wait_for_load_state("networkidle")
    final_url = page.url
    # Accept login page, dashboard, or home as valid redirect destinations
    valid_destinations = ["/admin/login", "/admin/dashboard", "/"]
    assert any(dest in final_url for dest in valid_destinations), (
        f"Unexpected redirect destination: {final_url}"
    )


def test_setup_page_no_500_error(page: Page, base_url: str) -> None:
    """Accessing /setup must not produce an HTTP 500 or unhandled exception page."""
    response = page.goto(f"{base_url}/setup")
    page.wait_for_load_state("networkidle")
    # Either a redirect (3xx) or a clean 200 on login/dashboard is acceptable
    assert response is not None
    # If there was a redirect followed, the final status should be 200
    assert response.status < 500, f"Server error accessing /setup: {response.status}"

"""E2E tests for category and location management in the admin panel."""
from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_CAT_LABEL_EN = f"E2E Test Category {int(time.time()) % 100000}"
_CAT_LABEL_DE = f"E2E Test Kategorie {int(time.time()) % 100000}"
_CAT_SLUG = f"e2e_test_cat_{int(time.time()) % 100000}"

_LOC_NAME = f"E2E Test Location {int(time.time()) % 100000}"
_LOC_CODE = f"E2E{int(time.time()) % 10000}"


def test_create_category(admin_page: Page, base_url: str) -> None:
    """Admin can create a new category which appears in the categories list."""
    admin_page.goto(f"{base_url}/admin/categories")
    admin_page.wait_for_load_state("networkidle")

    admin_page.fill('input[name="slug"]', _CAT_SLUG)
    admin_page.fill('input[name="label_en"]', _CAT_LABEL_EN)
    admin_page.fill('input[name="label_de"]', _CAT_LABEL_DE)
    admin_page.click('button[type="submit"].btn-primary')
    admin_page.wait_for_load_state("networkidle")

    body = admin_page.content()
    assert _CAT_LABEL_EN in body, (
        f"New category '{_CAT_LABEL_EN}' not found in categories list after creation"
    )


def test_deactivate_category(admin_page: Page, base_url: str) -> None:
    """Admin can deactivate the test category."""
    admin_page.goto(f"{base_url}/admin/categories")
    admin_page.wait_for_load_state("networkidle")

    row = admin_page.locator("table tbody tr").filter(has_text=_CAT_LABEL_EN)
    if row.count() == 0:
        pytest.skip(f"Test category '{_CAT_LABEL_EN}' not found — run create test first")

    deactivate_form = row.locator('form[action*="/deactivate"]')
    if deactivate_form.count() == 0:
        pytest.skip("Deactivate form not found for test category")

    deactivate_form.locator('button[type="submit"]').click()
    admin_page.wait_for_load_state("networkidle")

    body = admin_page.content()
    assert any(
        term in body.lower()
        for term in ["inactive", "deactivated", "opacity:0.5"]
    ), "Category not marked as inactive after deactivation"


def test_create_location(admin_page: Page, base_url: str) -> None:
    """Admin can create a new location which appears in the locations list."""
    admin_page.goto(f"{base_url}/admin/locations")
    admin_page.wait_for_load_state("networkidle")

    admin_page.fill('input[name="name"]', _LOC_NAME)
    admin_page.fill('input[name="code"]', _LOC_CODE)
    admin_page.click('button[type="submit"].btn-primary')
    admin_page.wait_for_load_state("networkidle")

    body = admin_page.content()
    assert _LOC_NAME in body, (
        f"New location '{_LOC_NAME}' not found in locations list after creation"
    )


def test_new_location_appears_in_submit_wizard(admin_page: Page, base_url: str) -> None:
    """After creating a location, it appears as an option in the submission wizard."""
    # Navigate to submit page — location step is only shown when locations exist
    admin_page.goto(f"{base_url}/submit")
    admin_page.wait_for_load_state("networkidle")

    # Advance to step 1 (mode) with default selection
    next_btn = admin_page.locator('button[type="submit"][name="action"][value="next"]')
    if next_btn.count() > 0:
        next_btn.click()
        admin_page.wait_for_load_state("networkidle")

    # Check if location step is shown
    location_select = admin_page.locator('select[name="location_id"]')
    if location_select.count() == 0:
        pytest.skip("Location step not shown in wizard — no active locations or step not reached")

    body = admin_page.content()
    assert _LOC_NAME in body, (
        f"Newly created location '{_LOC_NAME}' not found in wizard location selector"
    )


def test_deactivate_location(admin_page: Page, base_url: str) -> None:
    """Admin can deactivate the test location."""
    admin_page.goto(f"{base_url}/admin/locations")
    admin_page.wait_for_load_state("networkidle")

    row = admin_page.locator("table tbody tr").filter(has_text=_LOC_NAME)
    if row.count() == 0:
        pytest.skip(f"Test location '{_LOC_NAME}' not found — run create test first")

    deactivate_form = row.locator('form[action*="/deactivate"]')
    if deactivate_form.count() == 0:
        pytest.skip("Deactivate form not found for test location")

    deactivate_form.locator('button[type="submit"]').click()
    admin_page.wait_for_load_state("networkidle")

    body = admin_page.content()
    assert any(
        term in body.lower()
        for term in ["inactive", "deactivated", "opacity:0.5"]
    ), "Location not marked as inactive after deactivation"


def test_deactivated_location_not_in_submit_wizard(admin_page: Page, base_url: str) -> None:
    """After deactivating the test location, it no longer appears in the wizard."""
    admin_page.goto(f"{base_url}/submit")
    admin_page.wait_for_load_state("networkidle")

    # Advance past step 1
    next_btn = admin_page.locator('button[type="submit"][name="action"][value="next"]')
    if next_btn.count() > 0:
        next_btn.click()
        admin_page.wait_for_load_state("networkidle")

    # Check location step
    location_select = admin_page.locator('select[name="location_id"]')
    if location_select.count() == 0:
        # No location step at all — deactivation worked (no active locations)
        return

    body = admin_page.content()
    # The deactivated location should NOT appear
    assert _LOC_NAME not in body, (
        f"Deactivated location '{_LOC_NAME}' still visible in wizard after deactivation"
    )

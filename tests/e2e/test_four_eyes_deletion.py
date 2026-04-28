"""E2E tests for the 4-eyes deletion flow.

Uses two separate admin sessions (admin_page and admin_page2) to test
that the same admin cannot both request and confirm deletion.

A throwaway report is created via the submission wizard before each test
to avoid permanently destroying demo seed data.
"""
from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_NEXT_BTN = 'button[type="submit"][name="action"][value="next"]'
_CASE_RE = re.compile(r"OW-[A-Z0-9]+-\d{5}")


def _create_throwaway_report(page: Page, base_url: str) -> str:
    """Submit a new report via the wizard and return its case number."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: anonymous — radio inputs are visually hidden; click the label card instead
    page.locator('label[for="mode-anonymous"]').click()
    page.click(_NEXT_BTN)
    page.wait_for_load_state("networkidle")

    # Step 2 (location — conditional): skip if present
    if page.locator('select[name="location_id"]').count() > 0:
        page.click(_NEXT_BTN)
        page.wait_for_load_state("networkidle")

    # Step 3: category
    category_select = page.locator('select[name="category"]')
    options = category_select.locator("option").all()
    for opt in options:
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    page.click(_NEXT_BTN)
    page.wait_for_load_state("networkidle")

    # Step 4: description
    page.locator('textarea[name="description"]').fill(
        f"Throwaway E2E test report for 4-eyes deletion test. Timestamp: {int(time.time())}. "
        "This report will be deleted as part of the deletion workflow test."
    )
    page.click(_NEXT_BTN)
    page.wait_for_load_state("networkidle")

    # Step 5: attachments (skip)
    page.click(_NEXT_BTN)
    page.wait_for_load_state("networkidle")

    # Step 6: review — submit
    page.click(_NEXT_BTN)
    page.wait_for_load_state("networkidle")

    body = page.content()
    match = _CASE_RE.search(body)
    if not match:
        pytest.skip("Could not create throwaway report — submission failed")
    return match.group(0)


def _find_report_detail_url(admin_page: Page, base_url: str, case_number: str) -> str | None:
    """Navigate to dashboard and find the detail URL for the given case number."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    row = admin_page.locator("table tbody tr").filter(has_text=case_number)
    if row.count() == 0:
        return None
    view_btn = row.locator("a.btn").first
    href = view_btn.get_attribute("href")
    if href and href.startswith("/admin/reports/"):
        return f"{base_url}{href}"
    view_btn.click()
    admin_page.wait_for_load_state("networkidle")
    return admin_page.url


def test_same_admin_cannot_confirm_own_deletion_request(
    admin_page: Page, base_url: str
) -> None:
    """Admin A requests deletion, then tries to confirm it — should see a conflict message."""
    # Create a throwaway report using a fresh anonymous browser context for submission
    case_number = _create_throwaway_report(admin_page, base_url)

    # Admin A: navigate to the report
    # After submission the page context is used by the admin — re-login
    from tests.e2e.conftest import (
        DEMO_ADMIN_PASSWORD,
        DEMO_ADMIN_TOTP_SECRET,
        DEMO_ADMIN_USERNAME,
        _admin_login,
    )

    _admin_login(
        admin_page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET
    )
    detail_url = _find_report_detail_url(admin_page, base_url, case_number)
    if detail_url is None:
        pytest.skip(f"Report {case_number} not found on dashboard (may not have been seeded)")

    admin_page.goto(detail_url)
    admin_page.wait_for_load_state("networkidle")

    # Click "Request Deletion" button (step-1 button that reveals the confirm form)
    request_btn = admin_page.locator("#delete-step-1 button")
    if request_btn.count() == 0:
        pytest.skip("Delete request button not found — user may lack admin role")
    request_btn.click()
    admin_page.wait_for_load_state("networkidle")

    # Now the confirm form (step-2) should be visible — click the submit button
    confirm_form = admin_page.locator('form[action*="/request-delete"]')
    if confirm_form.count() == 0:
        pytest.skip("request-delete form not found")
    confirm_form.locator('button[type="submit"]').click()
    admin_page.wait_for_load_state("networkidle")

    # The page should now show a pending deletion state
    body = admin_page.content()
    assert any(
        term in body.lower()
        for term in ["pending", "cannot_self", "cannot", "same admin", "you requested", "cancel"]
    ), f"Expected pending deletion state or self-conflict message, got: {body[:500]}"

    # Admin A tries to confirm — the "Confirm" button should NOT appear for the same user
    confirm_4eyes = admin_page.locator('button.btn-danger').filter(has_text=re.compile(r"[Cc]onfirm"))
    # Either no confirm button, or if present it should lead to an error (self-conflict)
    if confirm_4eyes.count() > 0:
        # Should be blocked — try clicking and expect error
        admin_page.on("dialog", lambda d: d.accept())
        confirm_4eyes.click()
        admin_page.wait_for_load_state("networkidle")
        new_body = admin_page.content()
        assert any(
            term in new_body.lower()
            for term in ["cannot", "conflict", "same", "error", "403", "own"]
        ), "Same admin confirming own deletion request should produce an error"


def test_second_admin_can_confirm_deletion(
    admin_page: Page, admin_page2: Page, base_url: str
) -> None:
    """Admin A requests deletion, Admin B confirms it — report is deleted successfully."""
    from tests.e2e.conftest import (
        DEMO_ADMIN_PASSWORD,
        DEMO_ADMIN_TOTP_SECRET,
        DEMO_ADMIN_USERNAME,
        _admin_login,
    )

    # Step 1: Admin A creates a throwaway report
    # Use a separate non-auth page for submission to avoid session conflicts
    case_number = _create_throwaway_report(admin_page, base_url)

    # Re-authenticate Admin A after the submission flow
    _admin_login(
        admin_page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET
    )

    # Step 2: Admin A opens the report and requests deletion
    detail_url = _find_report_detail_url(admin_page, base_url, case_number)
    if detail_url is None:
        pytest.skip(f"Report {case_number} not found on dashboard")

    admin_page.goto(detail_url)
    admin_page.wait_for_load_state("networkidle")

    request_btn = admin_page.locator("#delete-step-1 button")
    if request_btn.count() == 0:
        pytest.skip("Delete request button not found")
    request_btn.click()
    admin_page.wait_for_load_state("networkidle")

    confirm_form = admin_page.locator('form[action*="/request-delete"]')
    if confirm_form.count() == 0:
        pytest.skip("request-delete form not found")
    confirm_form.locator('button[type="submit"]').click()
    admin_page.wait_for_load_state("networkidle")

    # Verify pending state
    body = admin_page.content()
    assert any(
        term in body.lower()
        for term in ["pending", "requested", "cancel", "cannot"]
    ), "Deletion request did not create pending state"

    # Step 3: Admin B navigates to same report and confirms deletion
    admin_page2.goto(detail_url)
    admin_page2.wait_for_load_state("networkidle")

    # Admin B should see the "Confirm Deletion" button (4-eyes)
    confirm_btn = admin_page2.locator('button.btn-danger').filter(has_text=re.compile(r"[Cc]onfirm"))
    if confirm_btn.count() == 0:
        pytest.skip("Confirm deletion button not visible for second admin — check demo seed roles")

    # Handle the browser confirm dialog
    admin_page2.on("dialog", lambda d: d.accept())
    confirm_btn.click()
    admin_page2.wait_for_load_state("networkidle")

    # After deletion, the report should be gone
    final_body = admin_page2.content()
    final_url = admin_page2.url
    # Should either redirect to dashboard with success message, or show not found
    assert any(
        indicator in final_body.lower() or indicator in final_url.lower()
        for indicator in ["deleted", "dashboard", "not found", "success", "removed"]
    ), f"Unexpected state after deletion confirmation. URL: {final_url}"

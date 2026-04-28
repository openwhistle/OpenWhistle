"""E2E tests for the whistleblower submission wizard.

The wizard has up to 6 steps (with location step conditional):
  Step 1: Mode selection (anonymous / confidential)
  Step 2: Location (only shown if locations exist)
  Step 3: Category selection
  Step 4: Description
  Step 5: Attachments (optional)
  Step 6: Review / confirm

Navigation: each step has a "Next" button (button[type="submit"][name="action"][value="next"]).
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

_NEXT_BTN = 'button[type="submit"][name="action"][value="next"]'
_BACK_BTN = 'button[type="submit"][name="action"][value="back"]'
_CASE_RE = re.compile(r"OW-[A-Z0-9]{4}-\d{5}")


def _advance_step(page: Page) -> None:
    """Click the Next/Submit button on the current wizard step."""
    page.click(_NEXT_BTN)
    page.wait_for_load_state("networkidle")


def _skip_location_if_present(page: Page) -> None:
    """If the location step (step 2) is shown, skip it by clicking Next without selecting."""
    # Check if we are on the location step by looking for location_id select
    if page.locator('select[name="location_id"]').count() > 0:
        _advance_step(page)


def _go_through_wizard_to_category(page: Page) -> None:
    """Navigate through step 1 (mode already set) and optional step 2 to reach category step."""
    _skip_location_if_present(page)


def test_submit_page_loads(page: Page, base_url: str) -> None:
    """The submission wizard landing page (step 1) loads correctly."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    assert "OpenWhistle" in page.title()
    # Step 1 mode cards should be visible
    expect(page.locator('input[name="submission_mode"]').first).to_be_visible()


def test_anonymous_submission_full_wizard(page: Page, base_url: str) -> None:
    """Anonymous submission flows through all steps and produces a case number + PIN."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: select anonymous mode (it is the default)
    page.check('input[name="submission_mode"][value="anonymous"]')
    _advance_step(page)

    # Step 2 (location — conditional): skip if present
    _skip_location_if_present(page)

    # Step 3: category — select first non-placeholder option
    page.wait_for_load_state("networkidle")
    category_select = page.locator('select[name="category"]')
    expect(category_select).to_be_visible()
    # Select the first real option (not the placeholder "")
    options = category_select.locator("option").all()
    for opt in options:
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    _advance_step(page)

    # Step 4: description
    page.wait_for_load_state("networkidle")
    desc_area = page.locator('textarea[name="description"]')
    expect(desc_area).to_be_visible()
    desc_area.fill(
        "This is an anonymous test report submitted via E2E tests. "
        "It contains enough characters to pass the minimum length validation."
    )
    _advance_step(page)

    # Step 5: attachments (skip — no file)
    page.wait_for_load_state("networkidle")
    _advance_step(page)

    # Step 6: review — submit the form
    page.wait_for_load_state("networkidle")
    _advance_step(page)

    # Success page: check for case number and PIN
    page.wait_for_load_state("networkidle")
    body = page.content()
    assert _CASE_RE.search(body) is not None, (
        f"No case number (OW-XXXX-NNNNN) found on success page. URL: {page.url}"
    )
    # PIN should be a UUID-like or long string
    assert re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", body
    ) is not None or re.search(r"[a-zA-Z0-9\-]{20,}", body) is not None, (
        "No PIN found on success page"
    )


def test_confidential_submission_full_wizard(page: Page, base_url: str) -> None:
    """Confidential submission fills name and contact fields and completes successfully."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: select confidential mode
    page.check('input[name="submission_mode"][value="confidential"]')
    # The confidential fields should become visible
    confidential_fields = page.locator("#confidential-fields")
    expect(confidential_fields).to_be_visible()
    page.fill('input[name="confidential_name"]', "E2E Test Submitter")
    page.fill('input[name="confidential_contact"]', "e2e-test@example.invalid")
    _advance_step(page)

    # Step 2 (location — conditional): skip if present
    _skip_location_if_present(page)

    # Step 3: category
    page.wait_for_load_state("networkidle")
    category_select = page.locator('select[name="category"]')
    expect(category_select).to_be_visible()
    options = category_select.locator("option").all()
    for opt in options:
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    _advance_step(page)

    # Step 4: description
    page.wait_for_load_state("networkidle")
    page.locator('textarea[name="description"]').fill(
        "This is a confidential test report submitted via E2E tests. "
        "Enough content to satisfy minimum length validation for the description field."
    )
    _advance_step(page)

    # Step 5: attachments (skip)
    page.wait_for_load_state("networkidle")
    _advance_step(page)

    # Step 6: review page — check confidential mode is displayed
    page.wait_for_load_state("networkidle")
    review_content = page.content()
    # Either the word "Confidential" or an equivalent translated label should appear
    assert any(
        word in review_content
        for word in ["confidential", "Confidential", "vertraulich", "Vertraulich"]
    ), "Confidential mode not shown on review page"
    _advance_step(page)

    # Success page
    page.wait_for_load_state("networkidle")
    body = page.content()
    assert _CASE_RE.search(body) is not None, (
        f"No case number found on success page after confidential submission. URL: {page.url}"
    )


def test_submission_with_file_attachment(page: Page, base_url: str) -> None:
    """Submission with a file attachment shows the filename on the review page."""
    # Minimal valid PDF bytes
    fake_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"

    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: anonymous mode
    page.check('input[name="submission_mode"][value="anonymous"]')
    _advance_step(page)

    # Step 2 (location — conditional): skip if present
    _skip_location_if_present(page)

    # Step 3: category
    page.wait_for_load_state("networkidle")
    category_select = page.locator('select[name="category"]')
    options = category_select.locator("option").all()
    for opt in options:
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    _advance_step(page)

    # Step 4: description
    page.wait_for_load_state("networkidle")
    page.locator('textarea[name="description"]').fill(
        "Test report with file attachment. Contains sufficient length to pass validation."
    )
    _advance_step(page)

    # Step 5: attachments — upload a fake PDF
    page.wait_for_load_state("networkidle")
    file_input = page.locator('input[type="file"][name="files"]')
    expect(file_input).to_be_attached()
    file_input.set_input_files(
        [{"name": "e2e_test_attachment.pdf", "mimeType": "application/pdf", "buffer": fake_pdf}]
    )
    _advance_step(page)

    # Step 6: review — check that the filename is shown
    page.wait_for_load_state("networkidle")
    review_content = page.content()
    assert "e2e_test_attachment.pdf" in review_content, (
        "Uploaded filename not shown on review page"
    )
    _advance_step(page)

    # Success page
    page.wait_for_load_state("networkidle")
    body = page.content()
    assert _CASE_RE.search(body) is not None, (
        f"No case number found on success page after attachment submission. URL: {page.url}"
    )

"""E2E tests for the whistleblower status check page.

Uses the demo report OW-DEMO-00002 (status=in_review, acknowledged).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import DEMO_CASE_IN_REVIEW

pytestmark = pytest.mark.e2e


def test_status_form_loads(page: Page, base_url: str) -> None:
    """GET /status shows the status check form with required inputs."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    assert "OpenWhistle" in page.title()
    expect(page.locator('input[name="case_number"]')).to_be_visible()
    expect(page.locator('input[name="pin"]')).to_be_visible()
    expect(page.locator("button.btn-primary")).to_be_visible()


def test_invalid_credentials_show_error(page: Page, base_url: str) -> None:
    """Submitting wrong credentials shows an error message."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="case_number"]', "OW-FAKE-99999")
    page.fill('input[name="pin"]', "wrong-pin-does-not-exist")
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    body = page.content()
    # Should show some error — either "invalid", "not found", or similar
    assert any(
        indicator in body.lower()
        for indicator in ["invalid", "error", "not found", "incorrect", "wrong"]
    ), "No error message shown for invalid credentials"
    # Must not show report details (progress-steps only appears on successful lookup)
    assert "progress-steps" not in body, "Report details shown despite invalid credentials"


def test_valid_credentials_show_report(page: Page, base_url: str) -> None:
    """Valid credentials for OW-DEMO-00002 display the report details."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="case_number"]', DEMO_CASE_IN_REVIEW["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_IN_REVIEW["pin"])
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    body = page.content()
    # Report case number should appear on the page
    assert DEMO_CASE_IN_REVIEW["case_number"] in body, (
        f"Case number {DEMO_CASE_IN_REVIEW['case_number']!r} not visible on status page"
    )
    # Status badge for in_review should be present
    assert any(
        term in body.lower()
        for term in ["in_review", "in review", "review"]
    ), "in_review status not visible on status page"


def test_ack_deadline_visible_for_acknowledged_report(page: Page, base_url: str) -> None:
    """The 7-day acknowledgement deadline section is shown for OW-DEMO-00002."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="case_number"]', DEMO_CASE_IN_REVIEW["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_IN_REVIEW["pin"])
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    body = page.content()
    # The deadlines section should be rendered — look for the acknowledgement date display
    # Template shows either "✓ acknowledged on date" or remaining days
    assert any(
        term in body
        for term in ["deadlines", "Deadlines", "acknowledged", "Acknowledged", "ack_done", "✓"]
    ), "Acknowledgement deadline section not visible"


def test_feedback_deadline_visible(page: Page, base_url: str) -> None:
    """The 3-month feedback deadline is shown for OW-DEMO-00002."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="case_number"]', DEMO_CASE_IN_REVIEW["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_IN_REVIEW["pin"])
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    body = page.content()
    # Feedback deadline section should be visible — template renders feedback_due_at date
    # or "pending" text when not yet set
    assert any(
        term in body.lower()
        for term in [
            "feedback",
            "3 month",
            "3-month",
            "days remaining",
            "feedback_due",
            "feedback_remaining",
        ]
    ), "Feedback deadline section not visible on status page"


def test_progress_steps_shown(page: Page, base_url: str) -> None:
    """The progress steps indicator is shown on a loaded report status page."""
    page.goto(f"{base_url}/status")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="case_number"]', DEMO_CASE_IN_REVIEW["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_IN_REVIEW["pin"])
    page.click("button.btn-primary")
    page.wait_for_load_state("networkidle")
    # The progress-steps div should exist
    expect(page.locator(".progress-steps")).to_be_visible()

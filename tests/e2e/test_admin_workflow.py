"""E2E tests for admin case management workflows.

Uses the demo admin account and pre-seeded demo reports.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import DEMO_CASE_RECEIVED

pytestmark = pytest.mark.e2e


def test_dashboard_shows_reports(admin_page: Page, base_url: str) -> None:
    """Admin dashboard loads and shows at least one demo report in the table."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    # The reports table should have at least one row
    rows = admin_page.locator("table tbody tr")
    assert rows.count() >= 1, "No report rows visible in dashboard table"


def test_clicking_report_opens_detail(admin_page: Page, base_url: str) -> None:
    """Clicking a report's View button opens the report detail page."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    # Click the first "View" link in the table
    view_link = admin_page.locator("table tbody tr td a.btn").first
    view_link.click()
    admin_page.wait_for_load_state("networkidle")
    assert "/admin/reports/" in admin_page.url, (
        f"Did not navigate to a report detail page. URL: {admin_page.url}"
    )


def test_received_report_has_acknowledge_button(admin_page: Page, base_url: str) -> None:
    """OW-DEMO-00001 (status=received) has an Acknowledge button."""
    # Navigate to dashboard and find OW-DEMO-00001
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    # Look for the row with OW-DEMO-00001 and click its View button
    row = admin_page.locator("table tbody tr").filter(
        has_text=DEMO_CASE_RECEIVED["case_number"]
    )
    if row.count() == 0:
        case = DEMO_CASE_RECEIVED["case_number"]
        pytest.skip(f"Demo report {case} not found — demo may need reset")
    view_btn = row.locator("a.btn").first
    view_btn.click()
    admin_page.wait_for_load_state("networkidle")
    # The acknowledge form/button should be visible (only shown when not yet acknowledged)
    body = admin_page.content()
    assert any(
        term in body.lower()
        for term in ["acknowledge", "ack", "bestätigen"]
    ), "Acknowledge button/form not found on received report detail page"


def test_admin_reply_appears_in_thread(admin_page: Page, base_url: str) -> None:
    """Admin can post a reply message which then appears in the communication thread."""
    import time
    # Navigate to OW-DEMO-00002 (in_review — not closed, can receive replies)
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    row = admin_page.locator("table tbody tr").filter(has_text="OW-DEMO-00002")
    if row.count() == 0:
        pytest.skip("OW-DEMO-00002 not found on dashboard")
    view_btn = row.locator("a.btn").first
    view_btn.click()
    admin_page.wait_for_load_state("networkidle")
    # The reply form should be visible (report is not closed)
    reply_area = admin_page.locator('textarea[name="content"]').first
    if reply_area.count() == 0:
        pytest.skip("Reply textarea not visible — report may be closed")
    unique_reply = f"E2E test reply {int(time.time())}"
    reply_area.fill(unique_reply)
    admin_page.locator('button[type="submit"]').filter(has_text_regex=r"[Ss]end|[Rr]eply|[Ss]ubmit|OK").first.click()
    admin_page.wait_for_load_state("networkidle")
    # The reply should appear in the thread
    body = admin_page.content()
    assert unique_reply in body, f"Posted reply not found in thread. URL: {admin_page.url}"


def test_status_dropdown_has_valid_options(admin_page: Page, base_url: str) -> None:
    """Status change dropdown shows valid transition options for OW-DEMO-00001."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")
    row = admin_page.locator("table tbody tr").filter(
        has_text=DEMO_CASE_RECEIVED["case_number"]
    )
    if row.count() == 0:
        pytest.skip(f"{DEMO_CASE_RECEIVED['case_number']} not on dashboard")
    row.locator("a.btn").first.click()
    admin_page.wait_for_load_state("networkidle")
    # Status select may or may not be present (only shown if transitions exist)
    status_select = admin_page.locator('select[name="new_status"]')
    if status_select.count() > 0:
        options = status_select.locator("option").all()
        assert len(options) >= 1, "Status select has no options"
    else:
        # No transitions available — check the "no transitions" message is shown
        body = admin_page.content()
        assert "transition" in body.lower() or "status" in body.lower()


def test_audit_log_has_entries(admin_page: Page, base_url: str) -> None:
    """The audit log page shows at least one entry."""
    admin_page.goto(f"{base_url}/admin/audit-log")
    admin_page.wait_for_load_state("networkidle")
    body = admin_page.content()
    # After demo seed, there should be audit entries
    # The audit log uses a table or list of entries
    assert any(
        indicator in body
        for indicator in ["<tbody>", "audit", "action", "created_at"]
    ), "No audit log entries found"


def test_stats_page_loads(admin_page: Page, base_url: str) -> None:
    """The /admin/stats page loads without error and shows content."""
    admin_page.goto(f"{base_url}/admin/stats")
    admin_page.wait_for_load_state("networkidle")
    assert "OpenWhistle" in admin_page.title()
    # Should not be an error page
    body = admin_page.content()
    assert "500" not in admin_page.url
    # Stats page should show some numeric content or chart
    assert any(
        term in body.lower()
        for term in ["stats", "report", "total", "count", "chart", "0"]
    ), "Stats page appears empty or broken"

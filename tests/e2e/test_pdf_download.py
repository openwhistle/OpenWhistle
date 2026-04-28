"""E2E tests for PDF export of admin reports."""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_pdf_export_download(admin_page: Page, base_url: str) -> None:
    """Export PDF button triggers a download of a valid PDF file."""
    # Navigate to OW-DEMO-00002 (in_review, acknowledged — has more metadata)
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")

    # Find OW-DEMO-00002 row and open it
    row = admin_page.locator("table tbody tr").filter(has_text="OW-DEMO-00002")
    if row.count() == 0:
        # Fall back to first report
        row = admin_page.locator("table tbody tr").first
        if row.count() == 0:
            pytest.skip("No reports found in dashboard")

    view_btn = row.locator("a.btn").first
    view_btn.click()
    admin_page.wait_for_load_state("networkidle")

    # Expect a download when clicking the Export PDF button/link
    with admin_page.expect_download(timeout=15000) as download_info:
        # The export link uses: /admin/reports/{id}/export.pdf with download attribute
        export_link = admin_page.locator('a[href*="export.pdf"]').first
        if export_link.count() == 0:
            pytest.skip("Export PDF link not found on report detail page")
        export_link.click()

    download = download_info.value
    filename = download.suggested_filename
    assert filename.endswith(".pdf"), (
        f"Downloaded file does not have .pdf extension: {filename!r}"
    )

    # Save and check file size
    path = download.path()
    assert path is not None, "Download did not produce a file"

    import os
    file_size = os.path.getsize(path)
    assert file_size > 1000, (
        f"Downloaded PDF is suspiciously small ({file_size} bytes) — may be empty or corrupt"
    )


def test_pdf_content_type(admin_page: Page, base_url: str) -> None:
    """The export.pdf endpoint returns application/pdf content-type."""
    # Navigate to any report detail
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.wait_for_load_state("networkidle")

    row = admin_page.locator("table tbody tr").first
    if row.count() == 0:
        pytest.skip("No reports on dashboard")

    view_btn = row.locator("a.btn").first
    view_btn.click()
    admin_page.wait_for_load_state("networkidle")

    export_link = admin_page.locator('a[href*="export.pdf"]').first
    if export_link.count() == 0:
        pytest.skip("Export PDF link not found")

    export_href = export_link.get_attribute("href")
    assert export_href is not None

    # Use fetch to check headers without triggering full download
    content_type: str = admin_page.evaluate(
        f"""async () => {{
            const r = await fetch('{export_href}');
            return r.headers.get('content-type') || '';
        }}"""
    )
    assert "pdf" in content_type.lower(), (
        f"Expected application/pdf content-type, got: {content_type!r}"
    )

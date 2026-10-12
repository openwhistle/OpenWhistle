"""Forms on the case page that answer with a file, not a page."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import DEMO_CASE_IN_REVIEW

pytestmark = pytest.mark.e2e


def test_an_identity_export_leaves_the_form_usable(admin_page: Page, base_url: str) -> None:
    """ "Export with identity" answers with a PDF download, so the page stays: the
    double-submit guard left the form marked as submitting and the button on "Please
    wait…", and Reveal and Export were dead until a reload."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.locator("tr", has_text=DEMO_CASE_IN_REVIEW["case_number"]).locator("a.btn").click()
    admin_page.fill("#identity-reason", "Checking the export keeps the form usable.")
    with admin_page.expect_download():
        admin_page.locator("button[formaction$='/export.pdf']").click()
    state = admin_page.evaluate(
        "(() => { const b = document.querySelector(\"button[formaction$='/export.pdf']\");"
        " return [b.disabled, b.form.dataset.owSubmitting || ''] })()"
    )
    assert state == [False, ""], state


def test_a_demo_case_number_can_be_linked(admin_page: Page, base_url: str) -> None:
    """The link field's pattern took OW-<year>-<5 digits> only: every demo case number
    (OW-DEMO-00002) and any lower-case entry the server accepts was refused by the
    browser."""
    admin_page.goto(f"{base_url}/admin/dashboard")
    admin_page.locator("a.btn[href^='/admin/reports/']").first.click()
    field = admin_page.locator("input[name='case_number']")
    for value in ("OW-DEMO-00002", "ow-2026-00001"):
        field.fill(value)
        assert field.evaluate("e => e.checkValidity()"), value

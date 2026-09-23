"""The whistleblower flow must work with JavaScript disabled (Tor Browser
"Safest" mode), and no page may scroll sideways on a phone."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, expect

pytestmark = pytest.mark.e2e


def test_confidential_fields_and_language_picker_work_without_js(
    browser: Browser, base_url: str
) -> None:
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(f"{base_url}/submit")

    name_field = page.locator('input[name="confidential_name"]')
    expect(name_field).to_be_hidden()
    page.locator('label[for="mode-confidential"]').click()
    expect(name_field).to_be_visible()

    page.locator("#lang-picker summary").click()
    expect(page.locator("#lang-picker .lang-picker-option").first).to_be_visible()
    context.close()


@pytest.mark.parametrize("path", ["/submit", "/status", "/admin/login"])
def test_no_horizontal_scroll_on_a_phone(browser: Browser, base_url: str, path: str) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(f"{base_url}{path}")
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    context.close()
    assert overflow <= 0, f"{path} scrolls sideways by {overflow}px at 390px"

"""On the plain-HTTP onion, navigator.clipboard is undefined, so the copy
buttons fall back to document.execCommand('copy'). A whistleblower's PIN cannot
be recovered, so the copy must confirm visibly on that path too — otherwise, on
exactly the connection the most at-risk reporter uses, there is no sign it
worked."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

_NEXT = 'button[type="submit"][name="action"][value="next"]'


def _submit_anonymous(page: Page, base_url: str) -> None:
    """Drive the anonymous wizard to the success page (case number + PIN)."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    page.locator('label[for="mode-anonymous"]').click()
    page.click(_NEXT)
    page.wait_for_load_state("networkidle")
    for _ in range(8):
        if page.locator('select[name="location_id"]').count():
            page.click(_NEXT)
        elif page.locator('select[name="category"]').count():
            sel = page.locator('select[name="category"]')
            for opt in sel.locator("option").all():
                if opt.get_attribute("value"):
                    sel.select_option(opt.get_attribute("value"))
                    break
            page.click(_NEXT)
        elif page.locator('textarea[name="description"]').count():
            page.locator('textarea[name="description"]').fill(
                "E2E copy-feedback test report, long enough to pass the minimum length rule."
            )
            page.click(_NEXT)
        elif page.locator(_NEXT).count():
            page.click(_NEXT)
        else:
            break
        page.wait_for_load_state("networkidle")


def test_pin_copy_confirms_without_the_clipboard_api(page: Page, base_url: str) -> None:
    _submit_anonymous(page, base_url)
    copy_buttons = page.locator('[data-action="copy"]')
    expect(copy_buttons).to_have_count(2)  # case number + PIN
    # Simulate the onion: remove the Clipboard API so the execCommand fallback runs.
    page.evaluate(
        "Object.defineProperty(navigator, 'clipboard', {get: () => undefined, configurable: true})"
    )
    pin_button = copy_buttons.last
    pin_button.click()
    # confirmCopied() disables the button (and swaps in the 'copied' label) on both
    # the Clipboard-API path and the execCommand fallback.
    expect(pin_button).to_be_disabled()

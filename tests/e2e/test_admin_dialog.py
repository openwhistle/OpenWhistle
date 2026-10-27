"""The admin add-dialog closes on a true backdrop click, Escape and Cancel — but
not on a mis-aimed click inside the panel's own padding, which would otherwise
dismiss a half-filled form. The backdrop handler keys on the click landing
outside the panel's box, not merely on the <dialog> element being the target."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def _open_category_dialog(admin_page: Page, base_url: str) -> None:
    admin_page.goto(f"{base_url}/admin/categories")
    admin_page.wait_for_load_state("networkidle")
    admin_page.click("[data-dialog-open]")
    admin_page.wait_for_timeout(150)
    admin_page.fill('input[name="slug"]', "wip_value")


def _panel_box(admin_page: Page) -> dict[str, float]:
    return admin_page.evaluate(
        "() => { const b = document.querySelector('dialog.dialog-panel')"
        ".getBoundingClientRect(); return {l:b.left, t:b.top, r:b.right, b:b.bottom}; }"
    )


def _dialog_open(admin_page: Page) -> bool:
    return bool(admin_page.evaluate("() => document.querySelector('dialog.dialog-panel').open"))


def test_click_in_the_panel_padding_does_not_close_the_dialog(
    admin_page: Page, base_url: str
) -> None:
    _open_category_dialog(admin_page, base_url)
    box = _panel_box(admin_page)
    # The top padding band: inside the panel's box, above the first field.
    admin_page.mouse.click((box["l"] + box["r"]) / 2, box["t"] + 6)
    admin_page.wait_for_timeout(150)
    assert _dialog_open(admin_page), "a click inside the panel padding closed the dialog"
    assert admin_page.input_value('input[name="slug"]') == "wip_value", "the typed value was lost"


def test_a_backdrop_click_closes_the_dialog(admin_page: Page, base_url: str) -> None:
    _open_category_dialog(admin_page, base_url)
    box = _panel_box(admin_page)
    # Well outside the panel's box — the backdrop.
    admin_page.mouse.click(box["l"] / 2, box["t"] / 2)
    admin_page.wait_for_timeout(150)
    assert not _dialog_open(admin_page), "a backdrop click did not close the dialog"


def test_escape_closes_the_dialog(admin_page: Page, base_url: str) -> None:
    _open_category_dialog(admin_page, base_url)
    admin_page.keyboard.press("Escape")
    admin_page.wait_for_timeout(150)
    assert not _dialog_open(admin_page), "Escape did not close the dialog"

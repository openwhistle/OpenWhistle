"""The preview follows the form before anything is saved (spec: The page)."""

from __future__ import annotations

import re

from playwright.sync_api import Page


def test_the_preview_follows_the_colour(admin_page: Page) -> None:
    admin_page.goto("/admin/branding")
    admin_page.fill("#bp-colour-hex", "#aa3300")
    admin_page.dispatch_event("#bp-colour-hex", "input")
    accent = admin_page.eval_on_selector(
        '.bp-panel[data-preview="light"]', "e => e.style.getPropertyValue('--bp-accent')"
    )
    dark = admin_page.eval_on_selector(
        '.bp-panel[data-preview="dark"]', "e => e.style.getPropertyValue('--bp-accent')"
    )
    assert accent == "#aa3300" and dark not in ("", "#aa3300")
    # The hint also names the 4.5:1 minimum; only the three measured ratios follow a label.
    shown = re.findall(r"(?:buttons|light|dark) \d+\.\d:1", admin_page.inner_text("#bp-contrast"))
    assert len(shown) == 3


def test_the_preview_follows_the_name(admin_page: Page) -> None:
    admin_page.goto("/admin/branding")
    admin_page.fill("#bp-name", "Acme Preview")
    texts = admin_page.locator("[data-preview-name]").all_inner_texts()
    assert texts == ["Acme Preview", "Acme Preview"]


def test_an_emptied_name_shows_the_fallback(admin_page: Page) -> None:
    admin_page.goto("/admin/branding")
    fallback = admin_page.get_attribute("#bp-name", "placeholder")
    assert fallback
    admin_page.fill("#bp-name", "A")
    admin_page.fill("#bp-name", "")
    texts = admin_page.locator("[data-preview-name]").all_inner_texts()
    assert texts == [fallback, fallback]


def test_a_wide_logo_never_widens_the_nav(admin_page: Page, tmp_path: object) -> None:
    import io
    from pathlib import Path

    from PIL import Image

    path = Path(str(tmp_path)) / "wide.png"
    buffer = io.BytesIO()
    Image.new("RGB", (4000, 50), (10, 10, 10)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    admin_page.set_viewport_size({"width": 390, "height": 844})
    admin_page.goto("/admin/branding")
    admin_page.set_input_files("#bp-logo_light", str(path))
    admin_page.wait_for_selector('img[data-preview-img="light"]', state="visible")
    width = admin_page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, width


def test_the_colour_controls_have_distinct_names(admin_page: Page) -> None:
    admin_page.goto("/admin/branding")
    picker = admin_page.get_by_label("Brand colour", exact=True)
    hex_field = admin_page.get_by_label("Hex value", exact=True)
    assert picker.get_attribute("id") == "bp-colour-picker"
    assert hex_field.get_attribute("id") == "bp-colour-hex"

"""Text on a solid fill reads in both themes (WCAG 1.4.3), measured in the browser.

axe skips what this catches: a one-character label ("Element content is too short")
lands in its "incomplete" list, not in its violations. White on the dark theme's light
fills shipped that way: the wizard's current step and the reporter's message icon at
2.34:1, the four-eyes "Request deletion" button at 2.78:1, the office's icon at 3.04:1.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    DEMO_CASE_PENDING,
    _admin_login,
)

pytestmark = pytest.mark.e2e

# Every element with a solid background and text of its own: its contrast, below the
# WCAG AA minimum (3:1 for large text, 4.5:1 otherwise). Closed <details> are opened.
_LOW_CONTRAST = r"""
() => {
  const lum = (c) => {
    const m = c.match(/[\d.]+/g).map(Number);
    const [r, g, b] = m.slice(0, 3).map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return [0.2126 * r + 0.7152 * g + 0.0722 * b, m[3] ?? 1];
  };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    const [lb, ab] = lum(s.backgroundColor);
    if (ab < 1 || s.opacity !== '1') continue;  // a solid fill only
    const text = [...el.childNodes]
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent.trim())
      .join('');
    if (!text) continue;
    const [lf, af] = lum(s.color);
    if (af < 1) continue;
    const ratio = (Math.max(lb, lf) + 0.05) / (Math.min(lb, lf) + 0.05);
    const size = parseFloat(s.fontSize);
    const bold = parseInt(s.fontWeight) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const name = `${el.tagName.toLowerCase()}.${[...el.classList].join('.')}`;
    if (ratio < need) out.push(`${name} "${text.slice(0, 20)}" ${ratio.toFixed(2)}`);
  }
  return out;
}
"""


def _low(page: Page) -> list[str]:
    page.wait_for_load_state("networkidle")
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    found: list[str] = page.evaluate(_LOW_CONTRAST)
    return found


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_on_a_fill_reads_on_reporter_pages(
    browser: Browser, base_url: str, theme: str
) -> None:
    ctx = browser.new_context(color_scheme=theme, base_url=base_url)
    page = ctx.new_page()
    found = []
    for path in ("/submit", "/status", "/admin/login"):
        page.goto(path)
        found += [f"{path}: {f}" for f in _low(page)]
    page.goto("/status")
    page.fill('input[name="case_number"]', DEMO_CASE_PENDING["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_PENDING["pin"])
    page.click("button.btn-primary[type='submit']")
    found += [f"/status case: {f}" for f in _low(page)]
    ctx.close()
    assert not found, found


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_on_a_fill_reads_on_admin_pages(browser: Browser, base_url: str, theme: str) -> None:
    ctx = browser.new_context(color_scheme=theme)
    page = ctx.new_page()
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    links: list[str] = page.evaluate(
        "[...document.querySelectorAll('.admin-nav a')].map(a => a.getAttribute('href'))"
    )
    report: str = page.evaluate(
        "document.querySelector('a[href^=\"/admin/reports/\"]').getAttribute('href')"
    )
    found = []
    for path in [*links, report]:
        page.goto(f"{base_url}{path}")
        found += [f"{path}: {f}" for f in _low(page)]
    ctx.close()
    assert not found, found

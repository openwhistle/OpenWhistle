"""Every page, both themes, phone and desktop: no accessibility violation of
impact serious or critical, no console error, no sideways scroll.

The counterpart of easywall's check:ui. The axe suite used to cover eight
pages in the light theme and failed on critical only; contrast failures in
the dark theme and on untested admin pages shipped unnoticed.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    _admin_login,
    run_axe,
)

pytestmark = pytest.mark.e2e

PUBLIC = ["/submit", "/status", "/admin/login"]
ADMIN = [
    "/admin/dashboard", "/admin/users", "/admin/stats", "/admin/audit-log",
    "/admin/categories", "/admin/locations", "/admin/retention", "/admin/system",
]


def _check(page: Page, errors: list[str], path: str, axe_source: str, label: str) -> list[str]:
    errors.clear()
    page.goto(path)
    page.wait_for_load_state("networkidle")
    problems = [f"{label}: console error: {e}" for e in errors]
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    if overflow > 0:
        problems.append(f"{label}: scrolls sideways by {overflow}px")
    if axe_source:
        for v in run_axe(page, axe_source):
            where = "; ".join(" ".join(n["target"]) for n in v["nodes"][:3])
            problems.append(f"{label}: axe {v['impact']} {v['id']} at {where}")
    return problems


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [390, 1440])
def test_ui_check(
    browser: Browser, base_url: str, axe_source: str, scheme: str, width: int
) -> None:
    context = browser.new_context(
        color_scheme=scheme, viewport={"width": width, "height": 900}, base_url=base_url
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    problems: list[str] = []
    for path in PUBLIC:
        problems += _check(page, errors, path, axe_source, f"{scheme} {width}px {path}")
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    report = page.locator('a[href^="/admin/reports/"]').first.get_attribute("href")
    for path in [*ADMIN, report or "/admin/dashboard"]:
        problems += _check(page, errors, path, axe_source, f"{scheme} {width}px {path}")
    context.close()
    assert not problems, "\n".join(problems)

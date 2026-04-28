"""E2E test configuration — fixtures for Playwright-based browser tests.

These tests require the full application stack to be running.
Start with: docker compose up -d (or the CI e2e workflow).
Default base URL: http://localhost:4009
Override with: pytest --base-url=http://your-host:port
"""
from __future__ import annotations

import urllib.request
from collections.abc import Generator

import pyotp
import pytest
from playwright.sync_api import Browser, BrowserContext, Page

# Demo credentials — published intentionally for the demo instance
DEMO_BASE_URL = "http://localhost:4009"
DEMO_ADMIN_USERNAME = "demo"
DEMO_ADMIN_PASSWORD = "demo"
DEMO_ADMIN_TOTP_SECRET = "JBSWY3DPEHPK3PXP"
DEMO_CM_USERNAME = "case_manager"
DEMO_CM_PASSWORD = "demo"

# Known demo report access credentials
DEMO_CASE_RECEIVED = {"case_number": "OW-DEMO-00001", "pin": "demo-pin-received-00001"}
DEMO_CASE_IN_REVIEW = {"case_number": "OW-DEMO-00002", "pin": "demo-pin-inreview-00002"}
DEMO_CASE_PENDING = {"case_number": "OW-DEMO-00003", "pin": "demo-pin-pending-00003"}
DEMO_CASE_CLOSED = {"case_number": "OW-DEMO-00004", "pin": "demo-pin-closed-00004"}

AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"


def _totp_now(secret: str = DEMO_ADMIN_TOTP_SECRET) -> str:
    return pyotp.TOTP(secret).now()


def _admin_login(page: Page, base_url: str, username: str, password: str, totp_secret: str) -> None:
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url("**/admin/login/mfa**")
    page.fill('input[name="totp_code"]', _totp_now(totp_secret))
    page.click('button[type="submit"]')
    page.wait_for_url("**/admin/dashboard**")


@pytest.fixture(scope="session")
def base_url() -> str:  # type: ignore[override]
    return DEMO_BASE_URL


@pytest.fixture(scope="session")
def axe_source() -> str:
    """Download axe-core once per session and cache the source."""
    try:
        with urllib.request.urlopen(AXE_CDN, timeout=10) as resp:  # noqa: S310
            return resp.read().decode("utf-8")
    except Exception:
        return ""  # gracefully skip axe if offline


@pytest.fixture
def admin_page(page: Page, base_url: str) -> Page:
    """Playwright Page already authenticated as the demo admin."""
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    return page


@pytest.fixture
def cm_page(page: Page, base_url: str) -> Page:
    """Playwright Page authenticated as the demo case_manager."""
    _admin_login(page, base_url, DEMO_CM_USERNAME, DEMO_CM_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    return page


@pytest.fixture
def admin_page2(browser: Browser, base_url: str) -> Generator[Page]:
    """Second admin browser context — for 4-eyes tests."""
    context: BrowserContext = browser.new_context()
    page = context.new_page()
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    yield page
    context.close()


def run_axe(page: Page, axe_source: str) -> list[dict]:  # type: ignore[type-arg]
    """Inject axe-core and return critical/serious violations."""
    if not axe_source:
        return []
    page.add_script_tag(content=axe_source)
    violations: list[dict] = page.evaluate(  # type: ignore[type-arg]
        """
        async () => {
            const results = await axe.run();
            return results.violations.filter(
                v => v.impact === 'critical' || v.impact === 'serious'
            );
        }
    """
    )
    return violations

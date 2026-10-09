"""E2E test configuration — fixtures for Playwright-based browser tests.

These tests require the full application stack to be running.
Start with: docker compose up -d (or the CI e2e workflow).
Default base URL: http://localhost:4009
Override with: pytest --base-url=http://your-host:port
"""

from __future__ import annotations

import hashlib
import http.server
import threading
from collections.abc import Generator
from functools import partial
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.built_site import builder

# The static marketing/docs site is served by its own nginx image. Build it and
# serve the build locally so browser tests against it (layout, theme/nav/scroll-spy
# behaviour) run standalone,
# without the FastAPI app or the review stack. Shared by every test module
# that needs it, so each one does not spin up its own copy of the same fixture.
# Session-wide, built once: pytest reorders parametrised tests across modules, and a
# module fixture rebuilt the whole site at every switch (hours in CI after P3).
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def docs_server_url(tmp_path_factory: pytest.TempPathFactory) -> Generator[str]:
    site = tmp_path_factory.mktemp("site") / "out"
    builder().build(_ROOT / "docs", site)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


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

# axe-core is vendored (tests/e2e/vendor/axe.min.js), never fetched. Renovate bumps
# AXE_VERSION; scripts/vendor_axe.py then writes the file and AXE_SHA256.
AXE_VERSION = "4.14.0"
AXE_SHA256 = "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878"
_AXE = Path(__file__).parent / "vendor" / "axe.min.js"


def _totp_now(secret: str = DEMO_ADMIN_TOTP_SECRET) -> str:
    """The demo accounts' static code. A real TOTP code is single-use (replay
    protection), and these tests log in several times within one 30 s step."""
    return "000000"


def _admin_login(page: Page, base_url: str, username: str, password: str, totp_secret: str) -> None:
    page.goto(f"{base_url}/admin/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    # Use btn-primary to avoid matching the language-picker submit buttons
    page.click("button.btn-primary[type='submit']")
    page.wait_for_selector('input[name="totp_code"]')
    page.fill('input[name="totp_code"]', _totp_now(totp_secret))
    page.click("button.btn-primary[type='submit']")
    page.wait_for_url("**/admin/dashboard**")


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:  # type: ignore[override]
    return request.config.getoption("base_url") or DEMO_BASE_URL


@pytest.fixture(scope="session")
def axe_source() -> str:
    """The vendored axe-core source, after checking it against AXE_SHA256."""
    data = _AXE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == AXE_SHA256, "axe.min.js does not match AXE_SHA256"
    return data.decode("utf-8")


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
    """Inject axe-core and return critical and serious violations.

    Serious includes color-contrast and link-in-text-block. It used to be a
    warning only, and every contrast failure on the site shipped green.
    """
    # Inject axe via page.evaluate (CDP Runtime.evaluate), NOT add_script_tag:
    # a <script> element is subject to the page's strict CSP (no 'unsafe-inline'),
    # whereas evaluate runs through the debugger protocol and is CSP-exempt.
    # Wrap in an arrow body so the minified UMD runs regardless of whether its
    # source is an expression or a series of statements.
    page.evaluate("() => { " + axe_source + "\n; }")
    violations: list[dict] = page.evaluate(  # type: ignore[type-arg]
        """
        async () => {
            const results = await axe.run();
            return results.violations.filter(v => ['critical', 'serious'].includes(v.impact));
        }
    """
    )
    return violations


def run_axe_warnings(page: Page, axe_source: str) -> list[dict]:  # type: ignore[type-arg]
    """Return serious (non-critical) axe violations for informational reporting."""
    violations: list[dict] = page.evaluate(  # type: ignore[type-arg]
        """
        async () => {
            const results = await axe.run();
            return results.violations.filter(v => v.impact === 'serious');
        }
    """
    )
    return violations

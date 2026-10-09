#!/usr/bin/env python3
"""Take the documentation screenshots into a checkout of openwhistle/website.

The screenshots are the website's files (docs/img/screens there); this script
writes them into the checkout given by --out or OW_WEBSITE_CHECKOUT and refuses
to run without one. Run against the local-review stack (docs-tech/local-review.md):

    podman compose -f docker-compose.e2e.yml -f docker-compose.review.yml up -d --build
    uv run python scripts/take_screenshots.py --out ../website
    podman compose -f docker-compose.e2e.yml -f docker-compose.review.yml down -v

Re-take these whenever the change alters the interface they document (a
template, site.css, or the theme/demo-banner behaviour) — not on every
release. tests/test_screenshots.py checks the *output* (both themes present,
viewport still above the breakpoint); it cannot tell whether a page's
content is stale, only a look at the images can.

One list of (name, path, setup) drives every shot: `path` is the page's own
URL, documentation of what it is; `setup` is what gets the browser there —
for the wizard and the admin pages that means driving the whole flow, not
just a GET.
"""

from __future__ import annotations

import argparse
import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page

BASE_URL = "http://127.0.0.1:4009"
CHECKOUT_ENV = "OW_WEBSITE_CHECKOUT"
SCREENS = Path("docs") / "img" / "screens"

# The admin two-column layout (`.admin-shell` in app/static/css/site.css) drops
# its sidebar to a single column at `max-width: 1023px` (that media query sits
# right next to the class, see site.css around line 3754). This viewport must
# stay wider than that breakpoint, or every admin screenshot shows the
# collapsed, single-column fallback instead of the layout the docs describe —
# see easywall's TestScreenshotsAreTakenAboveTheTwoColumnBreakpoint, which is
# the guard tests/test_screenshots.py adapts for this constant.
VIEWPORT_WIDTH = 1440
VIEWPORT_HEIGHT = 900
# The WebP for narrow screens (<picture>, quality 60): 640 px wide, 400 px for a 900 px shot.
MOBILE_WIDTH = 640

# The `ow-theme` localStorage key app/templates/base.html and
# app/static/js/site.js read before first paint.
THEME_STORAGE_KEY = "ow-theme"

DEMO_DESCRIPTION = (
    "Screenshot placeholder: a short description of a workplace safety "
    "concern, long enough to pass the minimum length check."
)

# Hides what only the review stack shows: the DEMO_MODE banner
# (app/templates/base.html), the demo credential panels on the login and
# status pages, and the LOCAL_REVIEW_LOGIN button. None of them is on an
# installed instance, so a docs screenshot must not carry them: the admin
# login shot once documented a maintainer-only button as part of the page.
_HIDE_REVIEW_ARTIFACTS_SCRIPT = """
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.demo-banner, .demo-credentials, .demo-legal')
    .forEach((el) => { el.style.display = 'none'; });
  // The demo login lays the form and the credentials out side by side; with
  // the credentials hidden the form would sit off-centre in an empty grid.
  document.querySelectorAll('.lg-with-demo')
    .forEach((el) => { el.classList.remove('lg-with-demo'); });
  const btn = document.getElementById('local-review-login-btn');
  if (btn) btn.closest('.panel').style.display = 'none';
});
"""


def _login_admin(page: Page) -> None:
    page.goto(f"{BASE_URL}/admin/login")
    # The button is hidden for the shots (see above); click() still submits it.
    with page.expect_navigation():
        page.evaluate("document.getElementById('local-review-login-btn').click()")
    page.wait_for_load_state("networkidle")


def _advance_wizard_step(page: Page) -> None:
    page.click("button[name=action][value=next]")
    page.wait_for_load_state("networkidle")


def _fill_wizard_through_review(page: Page) -> None:
    """Drive the whistleblower submission wizard from step 1 to the review step."""
    page.goto(f"{BASE_URL}/submit")
    page.check("#mode-anonymous")
    _advance_wizard_step(page)

    if page.query_selector("#location_id"):
        page.select_option("#location_id", index=1)
        _advance_wizard_step(page)

    page.select_option("#category", index=1)
    _advance_wizard_step(page)

    page.fill("#description", DEMO_DESCRIPTION)
    _advance_wizard_step(page)

    # Step 5, attachments: none to add.
    _advance_wizard_step(page)


def setup_submit_step1(page: Page) -> None:
    page.goto(f"{BASE_URL}/submit")


def setup_submit_review(page: Page) -> None:
    _fill_wizard_through_review(page)


def setup_submit_success(page: Page) -> None:
    _fill_wizard_through_review(page)
    _advance_wizard_step(page)


def setup_status(page: Page) -> None:
    page.goto(f"{BASE_URL}/status")


def setup_admin_login(page: Page) -> None:
    page.goto(f"{BASE_URL}/admin/login")


def setup_admin_dashboard(page: Page) -> None:
    _login_admin(page)
    page.goto(f"{BASE_URL}/admin/dashboard")
    page.wait_for_load_state("networkidle")


def setup_admin_report(page: Page) -> None:
    _login_admin(page)
    page.goto(f"{BASE_URL}/admin/dashboard")
    page.wait_for_load_state("networkidle")
    href = page.eval_on_selector("a[href^='/admin/reports/']", "el => el.getAttribute('href')")
    page.goto(f"{BASE_URL}{href}")
    page.wait_for_load_state("networkidle")


def setup_admin_system(page: Page) -> None:
    _login_admin(page)
    page.goto(f"{BASE_URL}/admin/system")
    page.wait_for_load_state("networkidle")


@dataclass(frozen=True)
class Screenshot:
    name: str
    path: str
    setup: Callable[[Page], None]


SCREENSHOTS: list[Screenshot] = [
    Screenshot("submit-step1", "/submit", setup_submit_step1),
    Screenshot("submit-review", "/submit", setup_submit_review),
    Screenshot("submit-success", "/submit", setup_submit_success),
    Screenshot("status", "/status", setup_status),
    Screenshot("admin-login", "/admin/login", setup_admin_login),
    Screenshot("admin-dashboard", "/admin/dashboard", setup_admin_dashboard),
    Screenshot("admin-report", "/admin/reports/{id}", setup_admin_report),
    Screenshot("admin-system", "/admin/system", setup_admin_system),
]


def _save_optimised_png(page_bytes: bytes, out_path: Path) -> None:
    """Re-save the PNG losslessly through Pillow's optimiser.

    Palette quantisation was tried and dropped: it turned the light theme's
    card surface (246, 246, 245) into near-white 253, so every light shot lost
    its cards against the page.
    """
    img = Image.open(io.BytesIO(page_bytes)).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)
    # Narrow screens get a 640 px WebP through <picture> (docs: .doc-shot): the page budget
    # (<= 100 KB for the first view) cannot carry a 170 KB PNG that lazy loading fetches anyway.
    small = img.resize(
        (MOBILE_WIDTH, round(img.height * MOBILE_WIDTH / img.width)), Image.Resampling.LANCZOS
    )
    small.save(out_path.with_name(out_path.stem + "-m.webp"), format="WEBP", quality=60, method=6)


def shoot(page: Page, name: str, theme: str, out_dir: Path) -> None:
    """Screenshot the current page into <out_dir>/<name>-<theme>.png.

    Grows the viewport to the document's height instead of passing
    `full_page=True`: easywall's TestScreenshotsGrowTheWindowInsteadOfCapturingBeyondIt
    documents why — a fixed/sticky element (here, `.admin-menu`'s sticky
    positioning and the session-expiry banner) stays laid out against the
    viewport it was rendered in, so a full-page capture beyond that window
    leaves it stranded partway down the image instead of tracking the page.
    """
    height = page.evaluate("document.documentElement.scrollHeight")
    height = max(height, VIEWPORT_HEIGHT)
    page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": height})
    # Let a sticky/fixed element settle after reflow, and the theme's colour
    # transitions finish: a shot taken sooner caught the light cards still
    # white, before their background had faded in.
    page.wait_for_timeout(600)

    out_path = out_dir / f"{name}-{theme}.png"
    png_bytes = page.screenshot(full_page=False)
    _save_optimised_png(png_bytes, out_path)

    page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
    size_kb = out_path.stat().st_size / 1024
    print(f"  wrote {out_path} ({size_kb:.0f} KiB)")


def _themed_context(browser: Browser, theme: str) -> BrowserContext:
    context = browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        locale="en-US",
        # The pages fade in (`.anim-in`); site.css cuts every animation to
        # 0.01 ms under reduced motion. Without it a shot can catch a form
        # half-faded, as the first admin-login shot did.
        reduced_motion="reduce",
    )
    context.add_cookies(
        [{"name": "ow-lang", "value": "en", "url": BASE_URL}],
    )
    context.add_init_script(
        f"try {{ localStorage.setItem('{THEME_STORAGE_KEY}', '{theme}'); }} catch (e) {{}}"
    )
    context.add_init_script(_HIDE_REVIEW_ARTIFACTS_SCRIPT)
    return context


def out_dir(argv: list[str] | None = None) -> Path:
    """The website checkout's screenshot folder; exits (code 2) without a checkout."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=os.environ.get(CHECKOUT_ENV) or None,
        help=f"checkout of openwhistle/website (default: ${CHECKOUT_ENV})",
    )
    checkout = parser.parse_args(argv).out
    if checkout is None:
        parser.error(f"give --out <website checkout> or set {CHECKOUT_ENV}")
    screens = Path(checkout) / SCREENS
    if not screens.is_dir():
        parser.error(
            f"{screens} is not a directory: --out must be a checkout of openwhistle/website"
        )
    return screens


def main(argv: list[str] | None = None) -> None:
    out = out_dir(argv)
    from playwright.sync_api import sync_playwright  # CI's test job has no Playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # Page outer, theme inner, and submit-success last: that shot
            # files a real report, and the dashboard shots must show the same
            # seeded cases in both themes, not one more in dark.
            order = sorted(SCREENSHOTS, key=lambda s: s.name == "submit-success")
            for shot in order:
                for theme in ("light", "dark"):
                    # A fresh context per shot: the whistleblower wizard's
                    # step lives in a server-side session keyed off a cookie,
                    # so a shared context left later shots on an earlier step.
                    context = _themed_context(browser, theme)
                    page = context.new_page()
                    shot.setup(page)
                    shoot(page, shot.name, theme, out)
                    context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()

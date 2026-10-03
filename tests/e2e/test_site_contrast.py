"""Every built page of openwhistle.net passes axe in both themes: contrast is computed, not read."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser

from tests.built_site import built, pages
from tests.e2e.conftest import run_axe

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_page_passes_axe(
    browser: Browser, docs_server_url: str, axe_source: str, theme: str
) -> None:
    # Reduced motion: the reveal animation would otherwise be measured mid-fade.
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, reduced_motion="reduce")
    ctx.add_init_script(f"localStorage.setItem('ow-theme','{theme}')")
    failures: dict[str, list[str]] = {}
    try:
        page = ctx.new_page()
        for path in pages():
            url = "/" + path.relative_to(built()).as_posix().removesuffix("index.html")
            page.goto(f"{docs_server_url}{url}")
            violations = run_axe(page, axe_source)
            if violations:
                failures[url] = [
                    f"{v['id']}: {n['target']}" for v in violations for n in v["nodes"][:5]
                ]
    finally:
        ctx.close()
    assert not failures, (theme, failures)

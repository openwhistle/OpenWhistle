"""The site in Chromium, served by its own container: the real CSP, search, the page budget."""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, CDPSession

from tests.built_site import built, pages

BASE = os.environ.get("WEBSITE_URL", "")
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not BASE, reason="WEBSITE_URL is not set")]
URLS = sorted("/" + p.relative_to(built()).as_posix().removesuffix("index.html") for p in pages())

# add_init_script runs the source as it is, so the arrow function is called at once.
_VIOLATIONS = """(() => { window.__csp = [];
  document.addEventListener('securitypolicyviolation',
    e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI)); })()"""


@pytest.mark.parametrize("url", URLS)
def test_no_page_breaks_its_csp(browser: Browser, url: str) -> None:
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    try:
        page = ctx.new_page()
        page.add_init_script(_VIOLATIONS)
        page.goto(BASE + url, wait_until="load")
        page.wait_for_timeout(300)
        violations = page.evaluate("window.__csp")
    finally:
        ctx.close()
    assert violations == [], f"{url}: {violations}"


def test_search_works_under_the_docs_csp(browser: Browser) -> None:
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        page.add_init_script(_VIOLATIONS)
        page.goto(BASE + "/en/docs/")
        page.keyboard.press("/")
        page.fill("#docs-search-input", "docker")
        page.wait_for_selector(".docs-search-results li", timeout=10_000)
        first = page.eval_on_selector(".docs-search-results a", "a => a.getAttribute('href')")
        violations = page.evaluate("window.__csp")
    finally:
        ctx.close()
    assert first.endswith("#highlight=docker") and violations == []


# Lighthouse's mobile preset: Slow 4G (150 ms, 1.6 Mbit/s down, 750 kbit/s up), 4x CPU slowdown.
_THROTTLE = {
    "offline": False,
    "latency": 150,
    "downloadThroughput": 200_000,
    "uploadThroughput": 93_750,
}
_METRICS = """() => new Promise(done => {
  let lcp = 0, cls = 0;
  new PerformanceObserver(l => { for (const e of l.getEntries()) lcp = e.startTime; })
    .observe({type: 'largest-contentful-paint', buffered: true});
  new PerformanceObserver(l => {
    for (const e of l.getEntries()) if (!e.hadRecentInput) cls += e.value; })
    .observe({type: 'layout-shift', buffered: true});
  setTimeout(() => done({lcp, cls}), 1000);
})"""


def _custom_fonts(cdp: CDPSession, selector: str) -> list[bool]:
    """Per platform font of the first match: is it a web font? [] when nothing matches."""
    cdp.send("DOM.enable")
    cdp.send("CSS.enable")
    root = cdp.send("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
    node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
    if not node:
        return []
    fonts = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
    return [bool(f.get("isCustomFont")) for f in fonts]


@pytest.mark.parametrize("url", URLS)
def test_the_first_view_stays_in_budget(browser: Browser, url: str) -> None:
    """Redesign spec, performance: <= 100 KB, LCP < 1.5 s, CLS 0, one host."""
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True
    )
    try:
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", _THROTTLE)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        sizes: dict[str, int] = {}
        urls: dict[str, str] = {}
        cdp.on(
            "Network.requestWillBeSent",
            lambda e: urls.__setitem__(e["requestId"], e["request"]["url"]),
        )
        cdp.on(
            "Network.loadingFinished",
            lambda e: sizes.__setitem__(e["requestId"], e["encodedDataLength"]),
        )
        page.goto(BASE + url, wait_until="load")
        metrics = page.evaluate(_METRICS)
        custom = _custom_fonts(cdp, "h1")
        mono = _custom_fonts(cdp, "code, pre")
    finally:
        ctx.close()
    foreign = sorted(
        {u for u in urls.values() if not u.startswith(BASE) and not u.startswith("data:")}
    )
    # A data: font is reported as a request of its own, but its bytes arrived inside the CSS.
    total = sum(n for key, n in sizes.items() if not urls.get(key, "").startswith("data:"))
    assert foreign == [], f"{url} asks another host: {foreign}"
    assert total <= 100 * 1024, f"{url}: first view {total} bytes"
    assert metrics["lcp"] < 1500, f"{url}: LCP {metrics['lcp']:.0f} ms"
    assert metrics["cls"] == 0, f"{url}: CLS {metrics['cls']}"
    # The fonts are inlined in the CSS: under the throttle the first view is drawn in them.
    assert custom and all(custom), f"{url}: the text fell back to a system font"
    assert all(mono), f"{url}: code fell back to a system font"

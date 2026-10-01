"""Pagefind, installed from PyPI, searches under the CSP the docs pages will get.

P0 spike of docs-tech/specs/2026-10-01-website-redesign-design.md. The site
loads no third-party code, so search runs on Pagefind's own pagefind.js, and
its WebAssembly needs 'wasm-unsafe-eval': the one relaxation the spec allows,
on docs pages only. The second test proves the first one can see a block: without the
directive, the WebAssembly compile fails.
"""

from __future__ import annotations

import http.server
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from playwright.sync_api import Browser

pytestmark = pytest.mark.e2e

DOCS_CSP = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
    "img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
STRICT_CSP = DOCS_CSP.replace(" 'wasm-unsafe-eval'", "")

PAGES = {
    "index.html": "<h1>Start</h1><p>Nothing to find here.</p>",
    "docs/tls/index.html": "<h1>TLS proxy</h1><p>Terminate TLS in front of the container.</p>",
    "docs/onion/index.html": "<h1>Onion address</h1><p>Offer the channel as an onion service.</p>",
}

SEARCH = """async () => {
  const violations = [];
  document.addEventListener('securitypolicyviolation',
    e => violations.push(e.violatedDirective + ' ' + e.blockedURI));
  let urls = [], error = null;
  try {
    const pagefind = await import('/pagefind/pagefind.js');
    await pagefind.init();
    const search = await pagefind.search('onion');
    urls = await Promise.all(search.results.map(async r => (await r.data()).url));
  } catch (e) { error = String(e); }
  return {urls, error, violations};
}"""


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pagefind-site")
    for rel, body in {**PAGES, "search.html": ""}.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{rel}</title>'
            f"</head><body><main>{body}</main></body></html>",
            encoding="utf-8",
        )
    try:
        subprocess.run(  # noqa: S603 — fixed argv, the module of a locked package
            [sys.executable, "-m", "pagefind", "--site", str(root)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        pytest.fail(f"pagefind failed ({e.returncode}): {e.stderr}")
    return root


def _search(browser: Browser, root: Path, csp: str) -> dict:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Content-Security-Policy", csp)
            super().end_headers()

        def log_message(self, *args) -> None:  # type: ignore[no-untyped-def]
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{server.server_port}/search.html")
        result = page.evaluate(SEARCH)
        ctx.close()
        return result
    finally:
        server.shutdown()


def test_search_works_under_the_docs_csp(browser: Browser, site: Path) -> None:
    result = _search(browser, site, DOCS_CSP)
    assert result == {"urls": ["/docs/onion/"], "error": None, "violations": []}


def test_without_wasm_unsafe_eval_the_csp_blocks_it(browser: Browser, site: Path) -> None:
    result = _search(browser, site, STRICT_CSP)
    # Chromium reports a blocked WebAssembly compile as a CompileError naming the
    # policy, not as a securitypolicyviolation event: `violations` stays empty.
    assert result["urls"] == [] and "Content Security" in (result["error"] or ""), result

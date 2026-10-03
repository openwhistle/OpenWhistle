"""What the built site looks like in a browser: computed values a static scan cannot see."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser

pytestmark = pytest.mark.e2e


def test_the_preloaded_fonts_are_the_ones_the_first_view_uses(
    browser: Browser, docs_server_url: str
) -> None:
    used: set[str] = set()
    preloaded: set[str] = set()
    for width in (1920, 390):
        for url in ("/en/", "/de/"):
            ctx = browser.new_context(viewport={"width": width, "height": 900})
            page = ctx.new_page()
            page.goto(f"{docs_server_url}{url}")
            page.evaluate("document.fonts.ready")
            used |= set(
                page.evaluate(
                    """() => { const out = new Set();
                 for (const el of document.querySelectorAll('body *')) {
                   const r = el.getBoundingClientRect();
                   if (r.bottom <= 0 || r.top >= innerHeight || !el.childNodes.length) continue;
                   if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))
                     continue;
                   const cs = getComputedStyle(el);
                   if (cs.visibility === 'hidden' || cs.display === 'none') continue;
                   const fam = cs.fontFamily.split(',')[0].replace(/['"]/g, '').trim();
                   const it = cs.fontStyle === 'italic' ? ' italic' : '';
                   out.add(fam + ' ' + cs.fontWeight + it);
                 }
                 return [...out]; }"""
                )
            )
            preloaded |= set(
                page.evaluate(
                    "() => [...document.querySelectorAll('link[rel=preload][as=font]')]"
                    ".map(l => l.href.split('/').pop())"
                )
            )
            ctx.close()
    sora = {u.split()[1] for u in used if u.startswith("Sora ") and "italic" not in u}
    matches = (re.search(r"sora-latin-(\d+)-normal", f) for f in preloaded)
    found = {m.group(1) for m in matches if m}
    assert found == sora, (sorted(sora), sorted(found))

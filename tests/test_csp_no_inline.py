"""Structural guard: templates must contain no CSP-'unsafe-inline' constructs.

The application ships a strict, nonce-based Content-Security-Policy with no
'unsafe-inline' in script-src or style-src (GHSA-gh23-4h5j-cqj8, finding #1).
Under that policy the browser silently drops:

  * inline event-handler attributes  (onclick="…", onchange="…", …)
  * inline style attributes           (style="…")
  * <script>/<style> blocks without the matching per-response nonce

Any of those would break the page at runtime. This test fails the build if a
template reintroduces one, so a regression cannot ship unnoticed — a real
browser only exercises the pages a test happens to visit, whereas this covers
every template deterministically.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"
_TEMPLATES = sorted(_TEMPLATE_DIR.rglob("*.html"))

# Inline event-handler attributes: on<name>= not preceded by a word char
# (so it never matches e.g. "person=" or Jinja tokens).
_INLINE_HANDLER_RE = re.compile(r"(?<![\w-])on[a-z]+\s*=", re.IGNORECASE)
_INLINE_STYLE_RE = re.compile(r'(?<![\w-])style\s*=\s*["\']')
# A <script>/<style> opening tag. We then require a nonce attribute on it.
_OPEN_TAG_RE = re.compile(r"<(script|style)(\s[^>]*)?>", re.IGNORECASE)
_NONCE_ATTR = "nonce="


def test_templates_exist() -> None:
    assert _TEMPLATES, "no templates found — path wrong?"


@pytest.mark.parametrize("tpl", _TEMPLATES, ids=lambda p: p.name)
def test_no_inline_event_handlers(tpl: Path) -> None:
    text = tpl.read_text(encoding="utf-8")
    hits = [m.group(0) for m in _INLINE_HANDLER_RE.finditer(text)]
    assert not hits, f"{tpl.name}: inline event handler(s) forbidden under CSP: {hits}"


@pytest.mark.parametrize("tpl", _TEMPLATES, ids=lambda p: p.name)
def test_no_inline_style_attributes(tpl: Path) -> None:
    text = tpl.read_text(encoding="utf-8")
    hits = _INLINE_STYLE_RE.findall(text)
    assert not hits, (
        f"{tpl.name}: {len(hits)} inline style attribute(s) forbidden under CSP — "
        "move them into a nonce'd <style> block or a CSS class"
    )


@pytest.mark.parametrize("tpl", _TEMPLATES, ids=lambda p: p.name)
def test_script_and_style_blocks_carry_nonce(tpl: Path) -> None:
    text = tpl.read_text(encoding="utf-8")
    offenders: list[str] = []
    for m in _OPEN_TAG_RE.finditer(text):
        attrs = (m.group(2) or "")
        if _NONCE_ATTR not in attrs:
            offenders.append(m.group(0)[:60])
    assert not offenders, (
        f"{tpl.name}: <script>/<style> block(s) without a CSP nonce: {offenders}"
    )

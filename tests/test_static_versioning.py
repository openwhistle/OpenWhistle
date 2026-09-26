"""Structural guard: static CSS/JS links must go through `static_url()`.

`/static/` is served with no far-future cache header and no hashed filename
(app/main.py just mounts the directory), so a browser that visited the site
before an upgrade keeps serving the old cached CSS/JS after a deploy, so a
CSS fix does not reach it. `static_url()` (app/templating.py)
appends `?v={app_version}`, which changes on every release and busts the
cache. This test fails the build if a template reintroduces a hand-typed
`/static/...` stylesheet or script URL that bypasses the helper.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"
_TEMPLATES = sorted(_TEMPLATE_DIR.rglob("*.html"))

# <link rel="stylesheet" href="...">, capturing the href value.
_STYLESHEET_RE = re.compile(
    r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*\bhref=["\']([^"\']*)["\']', re.IGNORECASE
)
# <script src="...">, capturing the src value.
_SCRIPT_SRC_RE = re.compile(r'<script\b[^>]*\bsrc=["\']([^"\']*)["\']', re.IGNORECASE)


def test_templates_exist() -> None:
    assert _TEMPLATES, "no templates found — path wrong?"


@pytest.mark.parametrize("tpl", _TEMPLATES, ids=lambda p: p.name)
def test_stylesheet_and_script_links_use_static_url_helper(tpl: Path) -> None:
    text = tpl.read_text(encoding="utf-8")
    offenders = [
        href
        for href in _STYLESHEET_RE.findall(text) + _SCRIPT_SRC_RE.findall(text)
        if href.startswith("/static/")
    ]
    assert not offenders, (
        f"{tpl.name}: static CSS/JS URL(s) bypassing static_url(): {offenders} — "
        "use {{ static_url('css/site.css') }} instead of a hand-typed /static/... path"
    )


def test_static_url_appends_version_query() -> None:
    from app.config import settings
    from app.templating import static_url

    assert static_url("css/site.css") == f"/static/css/site.css?v={settings.app_version}"

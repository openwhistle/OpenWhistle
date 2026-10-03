"""The site's stylesheets: which exist, who owns the tokens, and what every page links."""

from __future__ import annotations

import re
from pathlib import Path

from tests.built_site import built, page, pages, stylesheets

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "docs" / "assets" / "css"
ALWAYS = ["tokens.css", "fonts.css", "base.css"]
_DEFINITION = re.compile(r"(?<![\w-])(--[\w-]+)\s*:")


def _sheets(html: str) -> list[str]:
    return [p.name for p in stylesheets(html)]


def test_every_page_links_tokens_fonts_and_base_first() -> None:
    for path in pages():
        html = path.read_text(encoding="utf-8")
        assert _sheets(html)[:3] == ALWAYS, path.relative_to(built())


def test_only_tokens_css_defines_custom_properties() -> None:
    offenders = {
        sheet.name: sorted(set(_DEFINITION.findall(sheet.read_text(encoding="utf-8"))))
        for sheet in CSS.glob("*.css")
        if sheet.name != "tokens.css" and _DEFINITION.search(sheet.read_text(encoding="utf-8"))
    }
    assert not offenders, f"custom properties outside tokens.css: {offenders}"


def test_tokens_css_has_a_light_and_a_dark_block_with_the_same_colour_names() -> None:
    text = (CSS / "tokens.css").read_text(encoding="utf-8")
    light = re.search(r":root\s*\{([^}]*)\}", text)
    dark = re.search(r'\[data-theme="dark"\]\s*\{([^}]*)\}', text)
    assert light and dark
    dark_names = set(_DEFINITION.findall(dark.group(1)))
    colour_names = {
        n
        for n, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", light.group(1))
        if re.match(r"#|rgba?\(|color-mix", v.strip())
    }
    assert colour_names == dark_names, colour_names ^ dark_names


def test_tokens_css_names_the_three_font_families() -> None:
    light = re.search(r":root\s*\{([^}]*)\}", (CSS / "tokens.css").read_text(encoding="utf-8"))
    assert light
    fonts = dict(re.findall(r"(--font-[\w-]+)\s*:\s*([^;]+);", light.group(1)))
    assert fonts == {
        "--font-display": "'Sora', system-ui, sans-serif",
        "--font-body": "'Sora', system-ui, sans-serif",
        "--font-mono": "'JetBrains Mono', ui-monospace, monospace",
    }


def test_no_stylesheet_uses_an_undefined_token() -> None:
    defined = set(_DEFINITION.findall((CSS / "tokens.css").read_text(encoding="utf-8")))
    used = {
        (sheet.name, name)
        for sheet in CSS.glob("*.css")
        for name in re.findall(r"var\((--[\w-]+)", sheet.read_text(encoding="utf-8"))
    }
    missing = sorted((s, n) for s, n in used if n not in defined)
    assert not missing, missing


def test_the_retired_token_names_are_gone() -> None:
    retired = (
        "--bg-base", "--bg-surface", "--bg-raised", "--bg-overlay", "--nav-bg", "--footer-bg",
        "--text-primary", "--text-secondary", "--text-muted", "--border-subtle", "--border-default",
        "--border-strong", "--code-bg", "--code-text", "--sidebar-bg", "--red-alert",
    )  # fmt: skip
    for sheet in CSS.glob("*.css"):
        text = sheet.read_text(encoding="utf-8")
        found = [n for n in retired if re.search(re.escape(n) + r"(?![\w-])", text)]
        assert not found, (sheet.name, found)


def test_the_landing_pages_and_posts_share_one_token_sheet() -> None:
    for url in ("/en/", "/de/", "/en/docs/", "/en/changelog/"):
        assert "tokens.css" in _sheets(page(url)), url


PAGE_TYPES = {"home.css", "docs.css", "post.css", "page.css"}


def test_the_site_has_exactly_the_planned_sheets() -> None:
    assert {p.name for p in CSS.glob("*.css")} == set(ALWAYS) | PAGE_TYPES


def test_every_page_links_exactly_one_page_type_sheet() -> None:
    for path in pages():
        sheets = _sheets(path.read_text(encoding="utf-8"))
        assert len(sheets) == 4 and sheets[3] in PAGE_TYPES, (path.relative_to(built()), sheets)


APP_CSS = ROOT / "app" / "static" / "css" / "site.css"


def _scheme_rules(text: str) -> dict[str, str]:
    out = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        if m := re.search(r"color-scheme\s*:\s*([^;]+);", body):
            out[" ".join(selector.split())] = m.group(1).strip()
    return out


def test_each_theme_declares_its_own_color_scheme_in_site_and_app() -> None:
    """Chrome's Auto Dark Mode recolours a page that does not declare dark support; `light` alone
    does not opt out, `only light` does (https://developer.chrome.com/blog/auto-dark-theme)."""
    want = {'[data-theme="light"]': "only light", '[data-theme="dark"]': "dark"}
    for sheet in (CSS / "base.css", APP_CSS):
        assert _scheme_rules(sheet.read_text(encoding="utf-8")) == want, sheet

"""The site's stylesheets: which exist, who owns the tokens, and what every page links."""

from __future__ import annotations

import re
from pathlib import Path

from tests.built_site import built, page, pages, stylesheets
from tests.diagram_tools import renderer

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


def test_no_template_declares_a_color_scheme() -> None:
    """Only the two theme rules may; an inline `<style>` or include would override them."""
    decl = re.compile(r"(?<![\w-])color-scheme\s*:")
    files = [
        f
        for d in ("app/templates", "docs/_includes", "docs/_layouts")
        for f in (ROOT / d).rglob("*")
        if f.is_file()
    ]
    assert files
    assert [str(f) for f in files if decl.search(f.read_text(encoding="utf-8"))] == []


def _rules(text: str, media: str = "") -> dict[tuple[str, str], list[str]]:
    """(media, selector) -> sorted declarations, for flat sheets with @media one level deep."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out: dict[tuple[str, str], list[str]] = {}
    i = 0
    while (brace := text.find("{", i)) != -1:
        head = " ".join(text[i:brace].split())
        depth, end = 1, brace + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            end += 1
        body = text[brace + 1 : end - 1]
        if head.startswith("@media"):
            out.update(_rules(body, head))
        elif not head.startswith("@"):
            decls = sorted(" ".join(d.split()) for d in body.split(";") if d.strip())
            out[(media, head)] = decls
        i = end
    return out


# Selectors docs.css and page.css may style differently, each with its reason. Expected empty.
DOCS_PAGE_DIFFERENCES: set[tuple[str, str]] = set()


def test_docs_and_page_style_their_shared_selectors_alike() -> None:
    docs = _rules((CSS / "docs.css").read_text(encoding="utf-8"))
    page_ = _rules((CSS / "page.css").read_text(encoding="utf-8"))
    shared = docs.keys() & page_.keys()
    assert len(shared) > 30, sorted(shared)  # the docs layout both page types use
    drifted = sorted(k for k in shared - DOCS_PAGE_DIFFERENCES if docs[k] != page_[k])
    assert not drifted, drifted


# The same selector, styled differently in two page-type sheets, on purpose. Each entry names why.
PAGE_TYPE_DIFFERENCES = {
    # Home figures sit in grid rows that space them; docs figures sit in running text.
    ("home.css", "docs.css", ("", ".diagram, .doc-shot")),
    # docs.css: a safety net for any bare <pre>; post.css: the posts' code block itself.
    ("docs.css", "post.css", ("", "pre")),
    # One class name, two components: the blog index card (page.css), the post header (post.css).
    ("post.css", "page.css", ("", ".article-meta")),
    ("post.css", "page.css", ("", ".article-tag")),
    ("post.css", "page.css", ("", ".article-title")),
}


def test_no_selector_drifts_between_two_page_type_sheets() -> None:
    names = ["home.css", "docs.css", "post.css", "page.css"]
    sheets = {n: _rules((CSS / n).read_text(encoding="utf-8")) for n in names}
    drifted = sorted(
        (a, b, key)
        for i, a in enumerate(names)
        for b in names[i + 1 :]
        for key in sheets[a].keys() & sheets[b].keys()
        if sheets[a][key] != sheets[b][key] and (a, b, key) not in PAGE_TYPE_DIFFERENCES
    )
    assert not drifted, drifted
    stale = [
        (a, b, k)
        for a, b, k in PAGE_TYPE_DIFFERENCES
        if k not in sheets[a].keys() & sheets[b].keys()
    ]
    assert not stale, stale


_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB = re.compile(r"rgba?\([^)]*\)")
# Illustrations of other software's chrome, not brand colour: the macOS window buttons
# of the home page's terminal mockup.
FOREIGN_COLOURS = {"#ff5f57", "#febc2e", "#28c840"}


def _block(text: str, opener: str) -> dict[str, str]:
    """Custom properties of every rule with exactly this selector; later rules win."""
    bodies = re.findall(re.escape(opener) + r"\s*\{([^}]*)\}", text)
    assert bodies, opener
    return {
        k: v.strip() for body in bodies for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


def test_every_colour_value_in_tokens_css_is_a_design_md_colour() -> None:
    """Literal colours come from DESIGN.md; anything else is derived from a token (color-mix)."""
    palette = renderer().palette()
    text = (CSS / "tokens.css").read_text(encoding="utf-8")
    for theme, opener in (("light", ":root"), ("dark", '[data-theme="dark"]')):
        allowed = set(palette[theme].values())
        for name, value in _block(text, opener).items():
            for literal in _HEX.findall(value):
                assert literal.lower() in allowed, (theme, name, literal)
            assert not _RGB.search(value), (
                theme,
                name,
                value,
                "derive with color-mix(in srgb, var(--x) N%, transparent)",
            )


def test_no_page_sheet_writes_a_colour_literal() -> None:
    for sheet in CSS.glob("*.css"):
        if sheet.name == "tokens.css":
            continue
        text = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)
        stray = {c.lower() for c in _HEX.findall(text)} - FOREIGN_COLOURS
        stray |= set(_RGB.findall(text))
        assert not stray, (sheet.name, sorted(stray))


# App token -> DESIGN.md key. Brand-derived tokens (--brand-primary, --accent, --accent-subtle,
# --cta-bg, --cta-bg-hover) are excluded: an operator re-brands them through brand.primary_color.
APP_TOKENS = {
    "--canvas": "canvas",
    "--surface-card": "surface",
    "--bg-code": "surface",
    "--surface-dark": "inverse",
    "--ink": "ink",
    "--body-text": "body",
    "--muted": "muted",
    "--hairline": "hairline",
    "--border-strong": "hairline-strong",
    "--danger": "danger",
    "--danger-subtle": "danger-weak",
    "--danger-hover": "danger-strong",
    "--warning": "warning",
    "--warning-subtle": "warning-weak",
    "--success": "success",
    "--success-subtle": "success-weak",
    "--info": "info",
    "--info-subtle": "info-weak",
    "--on-dark": "inverse-ink",
    "--muted-on-dark": "inverse-muted",
    "--cta-text": "accent-ink",
}


def _hex6(value: str) -> str:
    v = value.strip().lower()
    return "#" + "".join(c * 2 for c in v[1:]) if re.fullmatch(r"#[0-9a-f]{3}", v) else v


def test_the_app_tokens_are_design_md_values() -> None:
    palette = renderer().palette()
    text = APP_CSS.read_text(encoding="utf-8")
    light = _block(text, ':root,\n[data-theme="light"]')
    dark = _block(text, '[data-theme="dark"]')
    for token, key in APP_TOKENS.items():
        assert _hex6(light[token]) == palette["light"][key], (token, "light", light[token])
        assert _hex6(dark.get(token, light[token])) == palette["dark"][key], (token, "dark")


_PAINT = re.compile(r'\b(?:fill|stroke|stop-color|color|style)="[^"]*(#[0-9a-fA-F]{3,8}\b|rgba?\()')


def test_no_page_paints_with_a_colour_literal() -> None:
    """Inline SVG takes currentColor and a sheet colours it: a literal skips the theme."""
    offenders = {
        str(path.relative_to(built())): sorted(set(_PAINT.findall(text)))
        for path in pages()
        if _PAINT.search(text := path.read_text(encoding="utf-8"))
    }
    assert not offenders, offenders
